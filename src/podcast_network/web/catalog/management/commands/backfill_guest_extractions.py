from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db.models import Exists, OuterRef

from podcast_network.extraction.openai_client import DEFAULT_EXTRACTION_MODEL, MissingOpenAIKeyError
from podcast_network.extraction.pipeline import extract_guest_batch, extract_guest_batch_async
from podcast_network.extraction.prompt import PROMPT_VERSION
from podcast_network.web.catalog.management.commands.extract_guests import (
    build_extractor,
    podcast_skips_guest_extraction,
    select_episodes,
)
from podcast_network.web.catalog.models import Episode, EpisodeGuestExtraction, GuestCandidate


class Command(BaseCommand):
    help = "Run resumable guest extraction backfill batches."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--batch-size", type=int, default=1000)
        parser.add_argument("--max-batches", type=int, default=1)
        parser.add_argument("--model", default=DEFAULT_EXTRACTION_MODEL)
        parser.add_argument("--prompt-version", default=PROMPT_VERSION)
        parser.add_argument("--provider", choices=["openai", "fake"], default="openai")
        parser.add_argument("--reasoning-effort", default="minimal")
        parser.add_argument("--run-label", default="guest-extraction-backfill")
        parser.add_argument("--concurrency", type=int, default=15)
        parser.add_argument(
            "--requests-per-minute",
            type=int,
            default=120,
            help="Throttle async provider request starts. Use 0 to disable.",
        )
        parser.add_argument("--retries", type=int, default=2)
        parser.add_argument("--retry-base-seconds", type=float, default=1.0)
        parser.add_argument("--sleep-between-batches", type=float, default=0)
        parser.add_argument(
            "--second-pass-review-band",
            action="store_true",
            help="Rerun first-pass review-band episodes with a stronger model.",
        )
        parser.add_argument("--review-min-confidence", type=float, default=0.75)
        parser.add_argument("--review-max-confidence", type=float, default=0.90)
        parser.add_argument(
            "--review-allow-high-confidence",
            action="store_true",
            help=(
                "Include review-band episodes even when first pass has a "
                "high-confidence candidate."
            ),
        )
        parser.add_argument("--second-pass-model", default="gpt-5-mini")
        parser.add_argument("--second-pass-provider", choices=["openai", "fake"], default="openai")
        parser.add_argument("--second-pass-reasoning-effort", default="medium")
        parser.add_argument("--second-pass-concurrency", type=int, default=15)
        parser.add_argument("--second-pass-requests-per-minute", type=int, default=90)
        parser.add_argument("--second-pass-retries", type=int, default=2)
        parser.add_argument("--second-pass-retry-base-seconds", type=float, default=1.0)
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show remaining and next-batch counts without calling the provider.",
        )

    def handle(self, *args: object, **options: object) -> None:
        batch_size = positive_int(options["batch_size"], "--batch-size")
        max_batches = positive_int(options["max_batches"], "--max-batches")
        concurrency = positive_int(options["concurrency"], "--concurrency")
        requests_per_minute = nonnegative_int(
            options["requests_per_minute"],
            "--requests-per-minute",
        )
        retries = nonnegative_int(options["retries"], "--retries")
        retry_base_seconds = nonnegative_float(
            options["retry_base_seconds"],
            "--retry-base-seconds",
        )
        review_min_confidence = nonnegative_float(
            options["review_min_confidence"],
            "--review-min-confidence",
        )
        review_max_confidence = nonnegative_float(
            options["review_max_confidence"],
            "--review-max-confidence",
        )
        if review_min_confidence >= review_max_confidence:
            raise CommandError("--review-min-confidence must be less than --review-max-confidence.")
        second_pass_concurrency = positive_int(
            options["second_pass_concurrency"],
            "--second-pass-concurrency",
        )
        second_pass_requests_per_minute = nonnegative_int(
            options["second_pass_requests_per_minute"],
            "--second-pass-requests-per-minute",
        )
        second_pass_retries = nonnegative_int(
            options["second_pass_retries"],
            "--second-pass-retries",
        )
        second_pass_retry_base_seconds = nonnegative_float(
            options["second_pass_retry_base_seconds"],
            "--second-pass-retry-base-seconds",
        )
        sleep_between_batches = nonnegative_float(
            options["sleep_between_batches"],
            "--sleep-between-batches",
        )
        model = str(options["model"])
        prompt_version = str(options["prompt_version"])
        provider = str(options["provider"])

        remaining = remaining_episode_count(model=model, prompt_version=prompt_version)
        next_batch_count = len(
            select_episodes(
                episode_ids=[],
                limit=batch_size,
                model=model,
                prompt_version=prompt_version,
                force=False,
            )
        )
        if options["dry_run"]:
            self.stdout.write(
                self.style.SUCCESS(
                    f"{remaining} episodes remain for {model} {prompt_version}. "
                    f"Next batch would process {next_batch_count} episodes."
                )
            )
            return

        try:
            extractor = build_extractor(
                provider=provider,
                model=model,
                reasoning_effort=str(options["reasoning_effort"]),
            )
        except MissingOpenAIKeyError as exc:
            raise CommandError(str(exc)) from exc
        second_pass_extractor = None
        if options["second_pass_review_band"]:
            try:
                second_pass_extractor = build_extractor(
                    provider=str(options["second_pass_provider"]),
                    model=str(options["second_pass_model"]),
                    reasoning_effort=str(options["second_pass_reasoning_effort"]),
                )
            except MissingOpenAIKeyError as exc:
                raise CommandError(str(exc)) from exc

        command_started_at = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        completed_batches = 0
        for batch_index in range(1, max_batches + 1):
            episodes = select_episodes(
                episode_ids=[],
                limit=batch_size,
                model=model,
                prompt_version=prompt_version,
                force=False,
            )
            if not episodes:
                self.stdout.write(self.style.SUCCESS("No remaining episodes to extract."))
                break

            run_label = f"{options['run_label']}:{command_started_at}:batch-{batch_index}"
            run = run_batch(
                episodes=episodes,
                extractor=extractor,
                model=model,
                provider=provider,
                prompt_version=prompt_version,
                concurrency=concurrency,
                requests_per_minute=requests_per_minute,
                retries=retries,
                retry_base_seconds=retry_base_seconds,
                run_label=run_label,
            )
            completed_batches += 1
            remaining = remaining_episode_count(model=model, prompt_version=prompt_version)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Batch {batch_index}/{max_batches} run {run.id} {run.status}: "
                    f"{run.episodes_succeeded} succeeded, {run.episodes_failed} failed. "
                    f"{remaining} episodes remain."
                )
            )
            if second_pass_extractor is not None:
                second_pass_episodes = select_second_pass_review_episodes(
                    first_pass_run=run,
                    first_pass_model=model,
                    second_pass_model=str(options["second_pass_model"]),
                    prompt_version=prompt_version,
                    review_min_confidence=review_min_confidence,
                    review_max_confidence=review_max_confidence,
                    require_no_high_confidence=not options["review_allow_high_confidence"],
                )
                if not second_pass_episodes:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Batch {batch_index}/{max_batches} second pass: "
                            "no review-band episodes selected."
                        )
                    )
                else:
                    second_pass_run_label = (
                        f"{options['run_label']}:{command_started_at}:"
                        f"batch-{batch_index}:second-pass"
                    )
                    second_pass_run = run_batch(
                        episodes=second_pass_episodes,
                        extractor=second_pass_extractor,
                        model=str(options["second_pass_model"]),
                        provider=str(options["second_pass_provider"]),
                        prompt_version=prompt_version,
                        concurrency=second_pass_concurrency,
                        requests_per_minute=second_pass_requests_per_minute,
                        retries=second_pass_retries,
                        retry_base_seconds=second_pass_retry_base_seconds,
                        run_label=second_pass_run_label,
                    )
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Batch {batch_index}/{max_batches} second pass run "
                            f"{second_pass_run.id} {second_pass_run.status}: "
                            f"{second_pass_run.episodes_succeeded} succeeded, "
                            f"{second_pass_run.episodes_failed} failed."
                        )
                    )

            if batch_index < max_batches and sleep_between_batches:
                time.sleep(sleep_between_batches)

        if completed_batches == 0:
            return
        self.stdout.write(self.style.SUCCESS(f"Completed {completed_batches} batch(es)."))


def run_batch(
    *,
    episodes: list[Episode],
    extractor,
    model: str,
    provider: str,
    prompt_version: str,
    concurrency: int,
    requests_per_minute: int,
    retries: int,
    retry_base_seconds: float,
    run_label: str,
):
    if concurrency > 1 and provider != "fake":
        return asyncio.run(
            extract_guest_batch_async(
                episodes,
                extractor=extractor,
                model=model,
                provider=provider,
                prompt_version=prompt_version,
                concurrency=concurrency,
                requests_per_minute=requests_per_minute,
                run_label=run_label,
                retries=retries,
                retry_base_seconds=retry_base_seconds,
            )
        )

    return extract_guest_batch(
        episodes,
        extractor=extractor,
        model=model,
        provider=provider,
        prompt_version=prompt_version,
        run_label=run_label,
    )


def remaining_episode_count(*, model: str, prompt_version: str) -> int:
    episodes = (
        Episode.objects.select_related("podcast")
        .exclude(
            guest_extractions__model=model,
            guest_extractions__prompt_version=prompt_version,
            guest_extractions__status=EpisodeGuestExtraction.Status.SUCCEEDED,
        )
        .iterator(chunk_size=5000)
    )
    return sum(1 for episode in episodes if not podcast_skips_guest_extraction(episode.podcast))


def select_second_pass_review_episodes(
    *,
    first_pass_run,
    first_pass_model: str,
    second_pass_model: str,
    prompt_version: str,
    review_min_confidence: float,
    review_max_confidence: float,
    require_no_high_confidence: bool = True,
) -> list[Episode]:
    first_pass_extractions = EpisodeGuestExtraction.objects.filter(
        episode=OuterRef("pk"),
        extraction_run=first_pass_run,
        model=first_pass_model,
        prompt_version=prompt_version,
        status=EpisodeGuestExtraction.Status.SUCCEEDED,
    )
    review_candidates = GuestCandidate.objects.filter(
        extraction__episode=OuterRef("pk"),
        extraction__extraction_run=first_pass_run,
        extraction__model=first_pass_model,
        extraction__prompt_version=prompt_version,
        extraction__status=EpisodeGuestExtraction.Status.SUCCEEDED,
        confidence__gte=review_min_confidence,
        confidence__lt=review_max_confidence,
    )
    high_confidence_candidates = GuestCandidate.objects.filter(
        extraction__episode=OuterRef("pk"),
        extraction__extraction_run=first_pass_run,
        extraction__model=first_pass_model,
        extraction__prompt_version=prompt_version,
        extraction__status=EpisodeGuestExtraction.Status.SUCCEEDED,
        confidence__gte=review_max_confidence,
    )
    second_pass_extractions = EpisodeGuestExtraction.objects.filter(
        episode=OuterRef("pk"),
        model=second_pass_model,
        prompt_version=prompt_version,
        status=EpisodeGuestExtraction.Status.SUCCEEDED,
    )
    queryset = (
        Episode.objects.select_related("podcast")
        .filter(Exists(first_pass_extractions), Exists(review_candidates))
        .exclude(Exists(second_pass_extractions))
        .order_by("-published_at", "id")
    )
    if require_no_high_confidence:
        queryset = queryset.exclude(Exists(high_confidence_candidates))
    return list(queryset)


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
