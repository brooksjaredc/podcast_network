from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from asgiref.sync import sync_to_async
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db.models import Exists, OuterRef

from podcast_network.cleaning import is_single_token_person_name
from podcast_network.extraction.models import GuestExtractionResult
from podcast_network.extraction.openai_client import DEFAULT_EXTRACTION_MODEL, MissingOpenAIKeyError
from podcast_network.extraction.pipeline import (
    AsyncStartRateLimiter,
    extract_async_with_retries,
    finalize_extraction_run,
    persist_failed_extraction,
    persist_successful_extraction,
)
from podcast_network.extraction.prompt import PROMPT_VERSION as FIRST_PASS_PROMPT_VERSION
from podcast_network.extraction.single_name_prompt import (
    PROMPT_VERSION,
    SingleNameCandidate,
    build_single_name_resolution_prompt,
)
from podcast_network.web.catalog.management.commands.extract_guests import build_extractor
from podcast_network.web.catalog.models import (
    Episode,
    EpisodeGuestExtraction,
    ExtractionRun,
    GuestCandidate,
)

FIRST_PASS_MODEL = "gpt-5-nano"


@dataclass(frozen=True)
class SingleNameEpisode:
    episode: Episode
    candidates: list[SingleNameCandidate]


class Command(BaseCommand):
    help = "Resolve one-word first-pass guest candidates with a separate LLM prompt."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--limit", type=int, default=25)
        parser.add_argument("--episode-id", type=int, action="append", default=[])
        parser.add_argument("--model", default=DEFAULT_EXTRACTION_MODEL)
        parser.add_argument("--prompt-version", default=PROMPT_VERSION)
        parser.add_argument("--first-pass-model", default=FIRST_PASS_MODEL)
        parser.add_argument("--first-pass-prompt-version", default=FIRST_PASS_PROMPT_VERSION)
        parser.add_argument("--provider", choices=["openai", "fake"], default="fake")
        parser.add_argument("--reasoning-effort", default="minimal")
        parser.add_argument(
            "--web-search",
            action="store_true",
            help="Allow the OpenAI Responses API web_search tool for extra context.",
        )
        parser.add_argument(
            "--max-tool-calls",
            type=int,
            default=2,
            help="Maximum web search tool calls per episode when --web-search is enabled.",
        )
        parser.add_argument("--concurrency", type=int, default=10)
        parser.add_argument("--requests-per-minute", type=int, default=120)
        parser.add_argument("--retries", type=int, default=2)
        parser.add_argument("--retry-base-seconds", type=float, default=1.0)
        parser.add_argument("--run-label", default="single-name-resolution")
        parser.add_argument("--force", action="store_true")
        parser.add_argument(
            "--sample-report",
            default="",
            help="Write selected prompt payloads to a Markdown report and do not call provider.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print selected episode count without calling provider.",
        )

    def handle(self, *args: object, **options: object) -> None:
        selected = select_single_name_episodes(
            episode_ids=list(options["episode_id"]),
            limit=positive_int(options["limit"], "--limit"),
            model=str(options["model"]),
            prompt_version=str(options["prompt_version"]),
            first_pass_model=str(options["first_pass_model"]),
            first_pass_prompt_version=str(options["first_pass_prompt_version"]),
            force=bool(options["force"]),
        )
        if options["sample_report"]:
            write_sample_report(selected, Path(str(options["sample_report"])))
            self.stdout.write(
                self.style.SUCCESS(
                    f"Wrote {len(selected)} single-name prompt examples to "
                    f"{options['sample_report']}."
                )
            )
            return
        if options["dry_run"]:
            self.stdout.write(
                self.style.SUCCESS(
                    f"{len(selected)} episodes selected for single-name resolution."
                )
            )
            return
        if not selected:
            self.stdout.write(self.style.WARNING("No single-name episodes selected."))
            return

        try:
            extractor = build_extractor(
                provider=str(options["provider"]),
                model=str(options["model"]),
                reasoning_effort=str(options["reasoning_effort"]),
                web_search=bool(options["web_search"]),
                max_tool_calls=nonnegative_int(options["max_tool_calls"], "--max-tool-calls"),
            )
        except MissingOpenAIKeyError as exc:
            raise CommandError(str(exc)) from exc

        run = asyncio.run(
            run_resolution_batch(
                selected=selected,
                extractor=extractor,
                model=str(options["model"]),
                provider=str(options["provider"]),
                prompt_version=str(options["prompt_version"]),
                concurrency=positive_int(options["concurrency"], "--concurrency"),
                requests_per_minute=nonnegative_int(
                    options["requests_per_minute"],
                    "--requests-per-minute",
                ),
                retries=nonnegative_int(options["retries"], "--retries"),
                retry_base_seconds=nonnegative_float(
                    options["retry_base_seconds"],
                    "--retry-base-seconds",
                ),
                run_label=str(options["run_label"]),
                web_search=bool(options["web_search"]),
                max_tool_calls=nonnegative_int(options["max_tool_calls"], "--max-tool-calls"),
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Single-name resolution run {run.id} {run.status}: "
                f"{run.episodes_succeeded} succeeded, {run.episodes_failed} failed, "
                f"{run.input_tokens} input tokens, {run.output_tokens} output tokens."
            )
        )


def select_single_name_episodes(
    *,
    episode_ids: list[int],
    limit: int,
    model: str,
    prompt_version: str,
    first_pass_model: str,
    first_pass_prompt_version: str,
    force: bool,
) -> list[SingleNameEpisode]:
    single_name_candidate = single_name_candidate_queryset(
        first_pass_model=first_pass_model,
        first_pass_prompt_version=first_pass_prompt_version,
    ).filter(extraction__episode=OuterRef("pk"))
    queryset = (
        Episode.objects.select_related("podcast")
        .filter(Exists(single_name_candidate))
        .order_by("-published_at", "id")
    )
    if episode_ids:
        queryset = queryset.filter(id__in=episode_ids)
        limit = max(limit, len(episode_ids))
    elif not force:
        successful_resolution = EpisodeGuestExtraction.objects.filter(
            episode=OuterRef("pk"),
            model=model,
            prompt_version=prompt_version,
            status=EpisodeGuestExtraction.Status.SUCCEEDED,
        )
        queryset = queryset.exclude(Exists(successful_resolution))

    episodes = list(queryset[:limit])
    candidates_by_episode = load_single_name_candidates(
        episode_ids=[episode.id for episode in episodes],
        first_pass_model=first_pass_model,
        first_pass_prompt_version=first_pass_prompt_version,
    )
    return [
        SingleNameEpisode(
            episode=episode,
            candidates=candidates_by_episode.get(episode.id, []),
        )
        for episode in episodes
    ]


def single_name_candidate_queryset(
    *,
    first_pass_model: str,
    first_pass_prompt_version: str,
):
    return (
        GuestCandidate.objects.filter(
            extraction__model=first_pass_model,
            extraction__prompt_version=first_pass_prompt_version,
            extraction__status=EpisodeGuestExtraction.Status.SUCCEEDED,
        )
        .exclude(normalized_name="")
        .exclude(normalized_name__contains=" ")
    )


def load_single_name_candidates(
    *,
    episode_ids: list[int],
    first_pass_model: str,
    first_pass_prompt_version: str,
) -> dict[int, list[SingleNameCandidate]]:
    output: dict[int, list[SingleNameCandidate]] = {}
    rows = (
        single_name_candidate_queryset(
            first_pass_model=first_pass_model,
            first_pass_prompt_version=first_pass_prompt_version,
        )
        .filter(extraction__episode_id__in=episode_ids)
        .select_related("extraction")
        .order_by("extraction__episode_id", "-confidence", "name")
    )
    for candidate in rows:
        output.setdefault(candidate.extraction.episode_id, []).append(
            SingleNameCandidate(
                name=candidate.name,
                confidence=candidate.confidence,
                evidence=candidate.evidence,
            )
        )
    return output


async def run_resolution_batch(
    *,
    selected: list[SingleNameEpisode],
    extractor,
    model: str,
    provider: str,
    prompt_version: str,
    concurrency: int,
    requests_per_minute: int,
    retries: int,
    retry_base_seconds: float,
    run_label: str,
    web_search: bool,
    max_tool_calls: int,
) -> ExtractionRun:
    run = await sync_to_async(ExtractionRun.objects.create)(
        model=model,
        provider=provider,
        prompt_version=prompt_version,
        episodes_requested=len(selected),
        metadata={
            "run_label": run_label,
            "purpose": "single-name-resolution",
            "concurrency": concurrency,
            "requests_per_minute": requests_per_minute,
            "retries": retries,
            "retry_base_seconds": retry_base_seconds,
            "web_search": web_search,
            "max_tool_calls": max_tool_calls,
        },
    )
    semaphore = asyncio.Semaphore(concurrency)
    rate_limiter = AsyncStartRateLimiter(requests_per_minute)

    async def resolve_one(item: SingleNameEpisode):
        prompt = build_single_name_resolution_prompt(item.episode, item.candidates)
        try:
            async with semaphore:
                await rate_limiter.acquire()
                if hasattr(extractor, "extract_async"):
                    result: GuestExtractionResult = await extract_async_with_retries(
                        extractor=extractor,
                        prompt=prompt,
                        retries=retries,
                        retry_base_seconds=retry_base_seconds,
                    )
                else:
                    result = await sync_to_async(extractor.extract)(prompt)
        except Exception as exc:
            return await sync_to_async(persist_failed_extraction)(
                episode=item.episode,
                extraction_run=run,
                model=model,
                prompt_version=prompt_version,
                input_text=prompt.input_text,
                error=str(exc),
            )
        return await sync_to_async(persist_successful_extraction)(
            episode=item.episode,
            extraction_run=run,
            model=model,
            prompt_version=prompt_version,
            input_text=prompt.input_text,
            result=filter_resolution_result(result),
        )

    outcomes = await asyncio.gather(*(resolve_one(item) for item in selected))
    return await sync_to_async(finalize_extraction_run)(run=run, outcomes=outcomes)


def write_sample_report(selected: list[SingleNameEpisode], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sections = ["# Single-Name Resolution Sample", ""]
    for item in selected:
        prompt = build_single_name_resolution_prompt(item.episode, item.candidates)
        sections.extend(
            [
                f"## Episode {item.episode.id}: {item.episode.podcast.name}",
                "",
                "```text",
                prompt.input_text,
                "```",
                "",
            ]
        )
    path.write_text("\n".join(sections), encoding="utf-8")


def filter_resolution_result(result: GuestExtractionResult) -> GuestExtractionResult:
    return GuestExtractionResult(
        guests=[
            guest
            for guest in result.guests
            if is_valid_resolved_name(guest.name)
        ],
        raw_response=result.raw_response,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )


def is_valid_resolved_name(name: str) -> bool:
    stripped = name.strip()
    if not stripped or "[" in stripped or "]" in stripped:
        return False
    lowered = stripped.casefold()
    if "not provided" in lowered or "unknown" in lowered:
        return False
    return not is_single_token_person_name(stripped)


def positive_int(value: object, option_name: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise CommandError(f"{option_name} must be positive.")
    return parsed


def nonnegative_int(value: object, option_name: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise CommandError(f"{option_name} must be zero or positive.")
    return parsed


def nonnegative_float(value: object, option_name: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise CommandError(f"{option_name} must be zero or positive.")
    return parsed
