from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db.models import Exists, OuterRef
from django.utils import timezone
from openai import OpenAI

from podcast_network.extraction.batch import BATCH_ENDPOINT, write_batch_jsonl
from podcast_network.extraction.openai_client import DEFAULT_EXTRACTION_MODEL
from podcast_network.extraction.pipeline import finalize_extraction_run
from podcast_network.extraction.prompt import PROMPT_VERSION
from podcast_network.web.catalog.management.commands.backfill_guest_extractions import (
    positive_int,
)
from podcast_network.web.catalog.management.commands.sync_guest_extraction_batch import (
    download_file_text,
    output_file_path,
    sync_output_lines,
)
from podcast_network.web.catalog.models import (
    Episode,
    EpisodeGuestExtraction,
    ExtractionRun,
    GuestCandidate,
)


class Command(BaseCommand):
    help = "Run a cloud-resident OpenAI Batch API second-pass review-band backfill."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--batch-size", type=int, default=1000)
        parser.add_argument("--wave-size", type=int, default=4)
        parser.add_argument("--first-pass-model", default=DEFAULT_EXTRACTION_MODEL)
        parser.add_argument("--second-pass-model", default="gpt-5-mini")
        parser.add_argument("--prompt-version", default=PROMPT_VERSION)
        parser.add_argument("--second-pass-reasoning-effort", default="medium")
        parser.add_argument("--review-min-confidence", type=float, default=0.75)
        parser.add_argument("--review-max-confidence", type=float, default=0.90)
        parser.add_argument(
            "--review-allow-high-confidence",
            action="store_true",
            help="Review episodes even when the first pass also found a high-confidence guest.",
        )
        parser.add_argument("--run-label", default="guest-extraction-cloud-second-pass")
        parser.add_argument("--poll-interval-seconds", type=int, default=300)
        parser.add_argument("--max-runtime-seconds", type=int, default=82800)
        parser.add_argument("--openai-timeout-seconds", type=float, default=60.0)
        parser.add_argument(
            "--output-dir",
            default="/tmp/podcast-network-batches",
            help="Directory for temporary batch input and output files.",
        )

    def handle(self, *args: object, **options: object) -> None:
        batch_size = positive_int(options["batch_size"], "--batch-size")
        wave_size = positive_int(options["wave_size"], "--wave-size")
        poll_interval_seconds = positive_int(
            options["poll_interval_seconds"],
            "--poll-interval-seconds",
        )
        max_runtime_seconds = positive_int(
            options["max_runtime_seconds"],
            "--max-runtime-seconds",
        )
        openai_timeout_seconds = float(options["openai_timeout_seconds"])
        if openai_timeout_seconds <= 0:
            raise CommandError("--openai-timeout-seconds must be positive.")

        first_pass_model = str(options["first_pass_model"])
        second_pass_model = str(options["second_pass_model"])
        prompt_version = str(options["prompt_version"])
        reasoning_effort = str(options["second_pass_reasoning_effort"])
        run_label = str(options["run_label"])
        output_dir = Path(str(options["output_dir"]))
        review_min_confidence = float(options["review_min_confidence"])
        review_max_confidence = float(options["review_max_confidence"])
        if review_min_confidence >= review_max_confidence:
            raise CommandError("--review-min-confidence must be less than --review-max-confidence.")

        client = OpenAI(timeout=openai_timeout_seconds, max_retries=2)
        started = time.monotonic()
        wave = 0

        while True:
            self.sync_active_runs(
                client=client,
                run_label=run_label,
                poll_interval_seconds=poll_interval_seconds,
                started=started,
                max_runtime_seconds=max_runtime_seconds,
            )
            remaining = count_remaining_review_episodes(
                first_pass_model=first_pass_model,
                second_pass_model=second_pass_model,
                prompt_version=prompt_version,
                review_min_confidence=review_min_confidence,
                review_max_confidence=review_max_confidence,
                require_no_high_confidence=not options["review_allow_high_confidence"],
            )
            self.stdout.write(f"Remaining episodes needing second pass: {remaining}.")
            if remaining == 0:
                self.stdout.write(self.style.SUCCESS("Second-pass guest extraction complete."))
                return
            if time.monotonic() - started > max_runtime_seconds:
                self.stdout.write(
                    self.style.WARNING(
                        "Max runtime reached before submitting another wave. "
                        "Run the job again to continue."
                    )
                )
                return

            wave += 1
            episodes = select_review_episodes(
                limit=batch_size * wave_size,
                first_pass_model=first_pass_model,
                second_pass_model=second_pass_model,
                prompt_version=prompt_version,
                review_min_confidence=review_min_confidence,
                review_max_confidence=review_max_confidence,
                require_no_high_confidence=not options["review_allow_high_confidence"],
            )
            chunks = chunked(episodes, batch_size)
            self.stdout.write(
                f"Submitting wave {wave}: {len(chunks)} batch(es), "
                f"{len(episodes)} episodes."
            )
            for index, chunk in enumerate(chunks, start=1):
                self.submit_batch(
                    client=client,
                    episodes=chunk,
                    wave=wave,
                    wave_batch_index=index,
                    wave_batch_count=len(chunks),
                    model=second_pass_model,
                    prompt_version=prompt_version,
                    reasoning_effort=reasoning_effort,
                    run_label=run_label,
                    output_dir=output_dir,
                )

    def sync_active_runs(
        self,
        *,
        client: OpenAI,
        run_label: str,
        poll_interval_seconds: int,
        started: float,
        max_runtime_seconds: int,
    ) -> None:
        while True:
            active_runs = list(
                ExtractionRun.objects.filter(
                    provider="openai-batch",
                    status=ExtractionRun.Status.RUNNING,
                    metadata__run_label=run_label,
                ).order_by("id")
            )
            if not active_runs:
                return
            pending = 0
            synced = 0
            failed = 0
            for run in active_runs:
                batch_id = run.metadata.get("batch_id")
                if not batch_id:
                    raise CommandError(f"ExtractionRun {run.id} has no batch_id metadata.")
                batch = client.batches.retrieve(str(batch_id))
                counts = getattr(batch, "request_counts", None)
                self.stdout.write(
                    f"Run {run.id} batch {batch.id}: {batch.status}; requests={counts}."
                )
                if batch.status == "completed":
                    self.sync_completed_batch(client=client, run=run, batch=batch)
                    synced += 1
                elif batch.status in {"failed", "expired", "cancelled"}:
                    self.mark_failed(run=run, batch=batch)
                    failed += 1
                else:
                    pending += 1
            self.stdout.write(
                f"Active batch check: {synced} synced, {failed} failed, "
                f"{pending} still pending."
            )
            if pending == 0:
                return
            if time.monotonic() - started > max_runtime_seconds:
                self.stdout.write(
                    self.style.WARNING(
                        "Max runtime reached while waiting for active batches. "
                        "Run the job again to continue syncing/submitting."
                    )
                )
                return
            self.stdout.write(f"Sleeping {poll_interval_seconds}s before next batch check.")
            time.sleep(poll_interval_seconds)

    def submit_batch(
        self,
        *,
        client: OpenAI,
        episodes: list[Episode],
        wave: int,
        wave_batch_index: int,
        wave_batch_count: int,
        model: str,
        prompt_version: str,
        reasoning_effort: str,
        run_label: str,
        output_dir: Path,
    ) -> ExtractionRun:
        timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        jsonl_path = (
            output_dir
            / f"guest_extraction_{model}_{timestamp}_second_pass_wave_{wave:04d}_"
            f"batch_{wave_batch_index:04d}.jsonl"
        )
        write_batch_jsonl(
            episodes,
            model=model,
            reasoning_effort=reasoning_effort,
            path=jsonl_path,
        )
        try:
            with jsonl_path.open("rb") as jsonl_file:
                uploaded_file = client.files.create(file=jsonl_file, purpose="batch")
            batch = client.batches.create(
                input_file_id=uploaded_file.id,
                endpoint=BATCH_ENDPOINT,
                completion_window="24h",
                metadata={
                    "run_label": run_label,
                    "prompt_version": prompt_version,
                    "phase": "second_pass",
                    "wave": str(wave),
                    "wave_batch_index": str(wave_batch_index),
                    "wave_batch_count": str(wave_batch_count),
                },
            )
        except Exception as exc:
            raise CommandError(
                f"OpenAI second-pass batch submission failed for wave {wave} "
                f"batch {wave_batch_index}: {exc}"
            ) from exc

        run = ExtractionRun.objects.create(
            model=model,
            provider="openai-batch",
            prompt_version=prompt_version,
            episodes_requested=len(episodes),
            metadata={
                "run_label": run_label,
                "coordinator_label": run_label,
                "phase": "second_pass",
                "batch_id": batch.id,
                "input_file_id": uploaded_file.id,
                "input_jsonl_path": str(jsonl_path),
                "endpoint": BATCH_ENDPOINT,
                "reasoning_effort": reasoning_effort,
                "wave": wave,
                "wave_batch_index": wave_batch_index,
                "wave_batch_count": wave_batch_count,
            },
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Submitted wave {wave} batch {wave_batch_index}/{wave_batch_count}: "
                f"run {run.id}, batch {batch.id}, {len(episodes)} episodes."
            )
        )
        return run

    def sync_completed_batch(self, *, client: OpenAI, run: ExtractionRun, batch) -> None:
        if not batch.output_file_id:
            raise CommandError(f"Batch {batch.id} completed without an output_file_id.")

        output_path = output_file_path(run, "output.jsonl")
        output_text = download_file_text(client, batch.output_file_id)
        output_path.write_text(output_text, encoding="utf-8")
        outcomes = sync_output_lines(run=run, output_text=output_text)

        metadata = {
            **run.metadata,
            "output_file_id": batch.output_file_id,
            "output_jsonl_path": str(output_path),
        }
        if batch.error_file_id:
            error_path = output_file_path(run, "errors.jsonl")
            error_path.write_text(
                download_file_text(client, batch.error_file_id),
                encoding="utf-8",
            )
            metadata["error_file_id"] = batch.error_file_id
            metadata["error_jsonl_path"] = str(error_path)
        run.metadata = metadata
        run.save(update_fields=["metadata"])
        finalize_extraction_run(run=run, outcomes=outcomes)
        self.stdout.write(
            self.style.SUCCESS(
                f"Synced run {run.id}: {run.episodes_succeeded} succeeded, "
                f"{run.episodes_failed} failed."
            )
        )

    def mark_failed(self, *, run: ExtractionRun, batch) -> None:
        errors = getattr(batch, "errors", None)
        run.status = ExtractionRun.Status.FAILED
        run.finished_at = timezone.now()
        run.metadata = {
            **run.metadata,
            "batch_status": batch.status,
            "batch_errors": errors.model_dump(mode="json") if errors else None,
        }
        run.save(update_fields=["status", "finished_at", "metadata"])


def select_review_episodes(
    *,
    limit: int,
    first_pass_model: str,
    second_pass_model: str,
    prompt_version: str,
    review_min_confidence: float,
    review_max_confidence: float,
    require_no_high_confidence: bool,
) -> list[Episode]:
    return list(
        review_episode_queryset(
            first_pass_model=first_pass_model,
            second_pass_model=second_pass_model,
            prompt_version=prompt_version,
            review_min_confidence=review_min_confidence,
            review_max_confidence=review_max_confidence,
            require_no_high_confidence=require_no_high_confidence,
        )[:limit]
    )


def count_remaining_review_episodes(
    *,
    first_pass_model: str,
    second_pass_model: str,
    prompt_version: str,
    review_min_confidence: float,
    review_max_confidence: float,
    require_no_high_confidence: bool,
) -> int:
    return review_episode_queryset(
        first_pass_model=first_pass_model,
        second_pass_model=second_pass_model,
        prompt_version=prompt_version,
        review_min_confidence=review_min_confidence,
        review_max_confidence=review_max_confidence,
        require_no_high_confidence=require_no_high_confidence,
    ).count()


def review_episode_queryset(
    *,
    first_pass_model: str,
    second_pass_model: str,
    prompt_version: str,
    review_min_confidence: float,
    review_max_confidence: float,
    require_no_high_confidence: bool,
):
    first_pass_extractions = EpisodeGuestExtraction.objects.filter(
        episode=OuterRef("pk"),
        model=first_pass_model,
        prompt_version=prompt_version,
        status=EpisodeGuestExtraction.Status.SUCCEEDED,
    )
    review_candidates = GuestCandidate.objects.filter(
        extraction__episode=OuterRef("pk"),
        extraction__model=first_pass_model,
        extraction__prompt_version=prompt_version,
        extraction__status=EpisodeGuestExtraction.Status.SUCCEEDED,
        confidence__gte=review_min_confidence,
        confidence__lt=review_max_confidence,
    )
    high_confidence_candidates = GuestCandidate.objects.filter(
        extraction__episode=OuterRef("pk"),
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
    return queryset


def chunked[T](items: list[T], size: int) -> list[list[T]]:
    return [items[index : index + size] for index in range(0, len(items), size)]
