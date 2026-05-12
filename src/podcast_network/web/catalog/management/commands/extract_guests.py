from __future__ import annotations

import asyncio

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db.models import Exists, OuterRef

from podcast_network.extraction.fake import FakeGuestExtractor
from podcast_network.extraction.openai_client import (
    DEFAULT_EXTRACTION_MODEL,
    MissingOpenAIKeyError,
    OpenAIGuestExtractor,
)
from podcast_network.extraction.pipeline import extract_guest_batch, extract_guest_batch_async
from podcast_network.extraction.prompt import PROMPT_VERSION
from podcast_network.web.catalog.models import Episode, EpisodeGuestExtraction


class Command(BaseCommand):
    help = "Extract episode guest names with an LLM-backed structured-output stage."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--limit", type=int, default=25)
        parser.add_argument("--episode-id", type=int, action="append", default=[])
        parser.add_argument("--model", default=DEFAULT_EXTRACTION_MODEL)
        parser.add_argument("--prompt-version", default=PROMPT_VERSION)
        parser.add_argument("--provider", choices=["openai", "fake"], default="fake")
        parser.add_argument("--reasoning-effort", default="minimal")
        parser.add_argument("--run-label", default="", help="Optional label stored on the run.")
        parser.add_argument(
            "--concurrency",
            type=int,
            default=15,
            help="Maximum concurrent provider calls. Values above 1 require an async extractor.",
        )
        parser.add_argument(
            "--requests-per-minute",
            type=int,
            default=120,
            help="Throttle async provider request starts. Use 0 to disable.",
        )
        parser.add_argument(
            "--retries",
            type=int,
            default=2,
            help="Retries per episode for async provider calls.",
        )
        parser.add_argument(
            "--retry-base-seconds",
            type=float,
            default=1.0,
            help="Initial retry sleep for async provider calls; doubles each retry.",
        )
        parser.add_argument("--force", action="store_true")

    def handle(self, *args: object, **options: object) -> None:
        model = str(options["model"])
        prompt_version = str(options["prompt_version"])
        provider = str(options["provider"])
        episodes = select_episodes(
            episode_ids=list(options["episode_id"]),
            limit=int(options["limit"]),
            model=model,
            prompt_version=prompt_version,
            force=bool(options["force"]),
        )
        if not episodes:
            self.stdout.write(self.style.WARNING("No episodes selected for extraction."))
            return

        try:
            extractor = build_extractor(
                provider=provider,
                model=model,
                reasoning_effort=str(options["reasoning_effort"]),
            )
        except MissingOpenAIKeyError as exc:
            raise CommandError(str(exc)) from exc

        concurrency = int(options["concurrency"])
        if concurrency < 1:
            raise CommandError("--concurrency must be positive.")
        retries = int(options["retries"])
        if retries < 0:
            raise CommandError("--retries must be zero or positive.")
        requests_per_minute = int(options["requests_per_minute"])
        if requests_per_minute < 0:
            raise CommandError("--requests-per-minute must be zero or positive.")
        retry_base_seconds = float(options["retry_base_seconds"])
        if retry_base_seconds < 0:
            raise CommandError("--retry-base-seconds must be zero or positive.")

        if concurrency > 1 and provider != "fake":
            if not hasattr(extractor, "extract_async"):
                raise CommandError(f"Provider {provider} does not support async extraction.")
            run = asyncio.run(
                extract_guest_batch_async(
                    episodes,
                    extractor=extractor,
                    model=model,
                    provider=provider,
                    prompt_version=prompt_version,
                    force=bool(options["force"]),
                    concurrency=concurrency,
                    run_label=str(options["run_label"]),
                    retries=retries,
                    retry_base_seconds=retry_base_seconds,
                    requests_per_minute=requests_per_minute,
                )
            )
        else:
            run = extract_guest_batch(
                episodes,
                extractor=extractor,
                model=model,
                provider=provider,
                prompt_version=prompt_version,
                force=bool(options["force"]),
                run_label=str(options["run_label"]),
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Extraction run {run.id} {run.status}: "
                f"{run.episodes_succeeded} succeeded, {run.episodes_failed} failed, "
                f"{run.input_tokens} input tokens, {run.output_tokens} output tokens."
            )
        )


def select_episodes(
    *,
    episode_ids: list[int],
    limit: int,
    model: str,
    prompt_version: str,
    force: bool,
) -> list[Episode]:
    queryset = (
        Episode.objects.select_related("podcast")
        .order_by("-published_at", "id")
    )
    if episode_ids:
        queryset = queryset.filter(id__in=episode_ids)
        limit = max(limit, len(episode_ids))
    elif not force:
        successful_extraction = EpisodeGuestExtraction.objects.filter(
            episode=OuterRef("pk"),
            model=model,
            prompt_version=prompt_version,
            status=EpisodeGuestExtraction.Status.SUCCEEDED,
        )
        queryset = queryset.exclude(Exists(successful_extraction))
    selected: list[Episode] = []
    for episode in queryset.iterator(chunk_size=1000):
        if podcast_skips_guest_extraction(episode.podcast):
            continue
        selected.append(episode)
        if len(selected) >= limit:
            break
    return selected


def podcast_skips_guest_extraction(podcast) -> bool:
    policy = (podcast.metadata or {}).get("extraction_policy") or {}
    return policy.get("skip_guest_extraction") is True


def build_extractor(
    *,
    provider: str,
    model: str,
    reasoning_effort: str,
    web_search: bool = False,
    max_tool_calls: int | None = None,
):
    if provider == "fake":
        return FakeGuestExtractor()
    return OpenAIGuestExtractor(
        model=model,
        reasoning_effort=reasoning_effort,
        web_search=web_search,
        max_tool_calls=max_tool_calls,
    )
