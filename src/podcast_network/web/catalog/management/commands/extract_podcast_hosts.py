from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from asgiref.sync import sync_to_async
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.db.models import Count, Exists, OuterRef
from django.utils import timezone

from podcast_network.cleaning import (
    clean_person_display_name,
    is_likely_english_podcast_name,
    is_single_token_person_name,
)
from podcast_network.extraction.host_models import PodcastHostExtractionResult
from podcast_network.extraction.host_openai_client import OpenAIPodcastHostExtractor
from podcast_network.extraction.host_prompt import PROMPT_VERSION, build_podcast_host_prompt
from podcast_network.extraction.openai_client import MissingOpenAIKeyError
from podcast_network.extraction.pipeline import AsyncStartRateLimiter, normalize_name
from podcast_network.extraction.pipeline import extract_async_with_retries as retry_async
from podcast_network.web.catalog.models import (
    ExtractionRun,
    HostCandidate,
    Podcast,
    PodcastHostExtraction,
)

DEFAULT_MODEL = "gpt-5-mini"


@dataclass(frozen=True)
class PodcastHostOutcome:
    podcast_id: int
    succeeded: bool
    error: str = ""


class Command(BaseCommand):
    help = "Extract regular podcast hosts and co-hosts from podcast metadata."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--limit", type=int, default=25)
        parser.add_argument("--podcast-id", type=int, action="append", default=[])
        parser.add_argument("--model", default=DEFAULT_MODEL)
        parser.add_argument("--prompt-version", default=PROMPT_VERSION)
        parser.add_argument("--reasoning-effort", default="medium")
        parser.add_argument(
            "--web-search",
            action="store_true",
            help="Allow the OpenAI Responses API web_search tool for extra context.",
        )
        parser.add_argument("--max-tool-calls", type=int, default=2)
        parser.add_argument(
            "--empty-from-run-id",
            type=int,
            default=0,
            help="Select podcasts that failed or produced no candidates in a previous host run.",
        )
        parser.add_argument("--concurrency", type=int, default=10)
        parser.add_argument("--requests-per-minute", type=int, default=120)
        parser.add_argument("--retries", type=int, default=2)
        parser.add_argument("--retry-base-seconds", type=float, default=1.0)
        parser.add_argument("--run-label", default="podcast-host-extraction")
        parser.add_argument("--force", action="store_true")
        parser.add_argument(
            "--sample-report",
            default="",
            help="Write selected prompt payloads to a Markdown report and do not call provider.",
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args: object, **options: object) -> None:
        podcasts = select_podcasts(
            podcast_ids=list(options["podcast_id"]),
            limit=positive_int(options["limit"], "--limit"),
            model=str(options["model"]),
            prompt_version=str(options["prompt_version"]),
            force=bool(options["force"]),
            empty_from_run_id=int(options["empty_from_run_id"]),
        )
        if options["sample_report"]:
            write_sample_report(podcasts, Path(str(options["sample_report"])))
            self.stdout.write(
                self.style.SUCCESS(
                    f"Wrote {len(podcasts)} podcast host prompt examples to "
                    f"{options['sample_report']}."
                )
            )
            return
        if options["dry_run"]:
            self.stdout.write(
                self.style.SUCCESS(f"{len(podcasts)} podcasts selected for host extraction.")
            )
            return
        if not podcasts:
            self.stdout.write(self.style.WARNING("No podcasts selected for host extraction."))
            return

        try:
            extractor = OpenAIPodcastHostExtractor(
                model=str(options["model"]),
                reasoning_effort=str(options["reasoning_effort"]),
                web_search=bool(options["web_search"]),
                max_tool_calls=nonnegative_int(options["max_tool_calls"], "--max-tool-calls"),
            )
        except MissingOpenAIKeyError as exc:
            raise CommandError(str(exc)) from exc

        run = asyncio.run(
            run_host_extraction_batch(
                podcasts=podcasts,
                extractor=extractor,
                model=str(options["model"]),
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
                f"Podcast host extraction run {run.id} {run.status}: "
                f"{run.episodes_succeeded} succeeded, {run.episodes_failed} failed, "
                f"{run.input_tokens} input tokens, {run.output_tokens} output tokens."
            )
        )


def select_podcasts(
    *,
    podcast_ids: list[int],
    limit: int,
    model: str,
    prompt_version: str,
    force: bool,
    empty_from_run_id: int = 0,
) -> list[Podcast]:
    queryset = Podcast.objects.order_by("name")
    if empty_from_run_id:
        empty_extractions = (
            PodcastHostExtraction.objects.filter(extraction_run_id=empty_from_run_id)
            .annotate(candidate_count=Count("host_candidates"))
            .filter(candidate_count=0)
            .values("podcast_id")
        )
        queryset = Podcast.objects.filter(id__in=empty_extractions).order_by("name")
    if podcast_ids:
        queryset = queryset.filter(id__in=podcast_ids)
        limit = max(limit, len(podcast_ids))
    elif not force and not empty_from_run_id:
        successful = PodcastHostExtraction.objects.filter(
            podcast=OuterRef("pk"),
            model=model,
            prompt_version=prompt_version,
            status=PodcastHostExtraction.Status.SUCCEEDED,
        )
        queryset = queryset.exclude(Exists(successful))
    selected: list[Podcast] = []
    for podcast in queryset.iterator(chunk_size=1000):
        if not is_likely_english_podcast_name(podcast.name):
            continue
        selected.append(podcast)
        if len(selected) >= limit:
            break
    return selected


async def run_host_extraction_batch(
    *,
    podcasts: list[Podcast],
    extractor: OpenAIPodcastHostExtractor,
    model: str,
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
        provider="openai",
        prompt_version=prompt_version,
        episodes_requested=len(podcasts),
        metadata={
            "run_label": run_label,
            "purpose": "podcast-host-extraction",
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

    async def extract_one(podcast: Podcast) -> PodcastHostOutcome:
        prompt = build_podcast_host_prompt(podcast)
        try:
            async with semaphore:
                await rate_limiter.acquire()
                result = await retry_async(
                    extractor=extractor,
                    prompt=prompt,
                    retries=retries,
                    retry_base_seconds=retry_base_seconds,
                )
        except Exception as exc:
            return await sync_to_async(persist_failed_extraction)(
                podcast=podcast,
                extraction_run=run,
                model=model,
                prompt_version=prompt_version,
                input_text=prompt.input_text,
                error=str(exc),
            )
        return await sync_to_async(persist_successful_extraction)(
            podcast=podcast,
            extraction_run=run,
            model=model,
            prompt_version=prompt_version,
            input_text=prompt.input_text,
            result=result,
        )

    outcomes = await asyncio.gather(*(extract_one(podcast) for podcast in podcasts))
    return await sync_to_async(finalize_run)(run=run, outcomes=outcomes)


def persist_failed_extraction(
    *,
    podcast: Podcast,
    extraction_run: ExtractionRun,
    model: str,
    prompt_version: str,
    input_text: str,
    error: str,
) -> PodcastHostOutcome:
    PodcastHostExtraction.objects.update_or_create(
        podcast=podcast,
        prompt_version=prompt_version,
        model=model,
        defaults={
            "extraction_run": extraction_run,
            "status": PodcastHostExtraction.Status.FAILED,
            "input_text": input_text,
            "error": error,
        },
    )
    return PodcastHostOutcome(podcast_id=podcast.id, succeeded=False, error=error)


def persist_successful_extraction(
    *,
    podcast: Podcast,
    extraction_run: ExtractionRun,
    model: str,
    prompt_version: str,
    input_text: str,
    result: PodcastHostExtractionResult,
) -> PodcastHostOutcome:
    with transaction.atomic():
        extraction, _ = PodcastHostExtraction.objects.update_or_create(
            podcast=podcast,
            prompt_version=prompt_version,
            model=model,
            defaults={
                "extraction_run": extraction_run,
                "status": PodcastHostExtraction.Status.SUCCEEDED,
                "input_text": input_text,
                "raw_response": result.raw_response,
                "error": "",
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
            },
        )
        extraction.host_candidates.all().delete()
        HostCandidate.objects.bulk_create(
            [
                HostCandidate(
                    extraction=extraction,
                    name=display_name,
                    normalized_name=normalize_name(display_name),
                    kind=host_kind(host.kind),
                    confidence=host.confidence,
                    evidence=host.evidence,
                )
                for host in result.hosts
                if host_kind(host.kind)
                for display_name in [clean_person_display_name(host.name)]
                if not is_single_token_person_name(display_name)
            ]
        )
    return PodcastHostOutcome(podcast_id=podcast.id, succeeded=True)


def finalize_run(*, run: ExtractionRun, outcomes: list[PodcastHostOutcome]) -> ExtractionRun:
    input_tokens = 0
    output_tokens = 0
    for extraction in run.podcast_host_extractions.all():
        input_tokens += extraction.input_tokens
        output_tokens += extraction.output_tokens

    run.episodes_succeeded = sum(outcome.succeeded for outcome in outcomes)
    run.episodes_failed = sum(not outcome.succeeded for outcome in outcomes)
    run.input_tokens = input_tokens
    run.output_tokens = output_tokens
    run.finished_at = timezone.now()
    if run.episodes_failed and run.episodes_succeeded:
        run.status = ExtractionRun.Status.PARTIAL
    elif run.episodes_failed:
        run.status = ExtractionRun.Status.FAILED
    else:
        run.status = ExtractionRun.Status.SUCCEEDED
    run.save()
    return run


def host_kind(value: str) -> str:
    normalized = value.strip().lower().replace("-", "")
    if normalized in {"host", "primary"}:
        return HostCandidate.Kind.HOST
    if normalized in {"cohost", "regular", "sidekick", "cast"}:
        return HostCandidate.Kind.COHOST
    return ""


def write_sample_report(podcasts: list[Podcast], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sections = ["# Podcast Host Extraction Sample", ""]
    for podcast in podcasts:
        prompt = build_podcast_host_prompt(podcast)
        sections.extend(
            [
                f"## Podcast {podcast.id}: {podcast.name}",
                "",
                "```text",
                prompt.input_text,
                "```",
                "",
            ]
        )
    path.write_text("\n".join(sections), encoding="utf-8")


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
