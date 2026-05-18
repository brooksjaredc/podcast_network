from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone
from openai import OpenAI

from podcast_network.extraction.batch import BATCH_ENDPOINT, write_batch_jsonl
from podcast_network.extraction.openai_client import DEFAULT_EXTRACTION_MODEL
from podcast_network.extraction.pipeline import finalize_extraction_run
from podcast_network.extraction.prompt import PROMPT_VERSION
from podcast_network.web.catalog.management.commands.backfill_guest_extractions import (
    nonnegative_int,
    positive_int,
    select_second_pass_review_episodes,
)
from podcast_network.web.catalog.management.commands.extract_guests import select_episodes
from podcast_network.web.catalog.management.commands.sync_guest_extraction_batch import (
    download_file_text,
    output_file_path,
    sync_output_lines,
)
from podcast_network.web.catalog.models import Episode, ExtractionRun


class Command(BaseCommand):
    help = "Run a resumable OpenAI Batch API guest extraction backfill coordinator."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--first-pass-batch-size", type=int, default=1000)
        parser.add_argument(
            "--max-first-pass-batches",
            type=int,
            default=1,
            help="Maximum first-pass batches to complete. Use 0 to run until exhausted.",
        )
        parser.add_argument("--first-pass-model", default=DEFAULT_EXTRACTION_MODEL)
        parser.add_argument("--first-pass-reasoning-effort", default="low")
        parser.add_argument("--second-pass-model", default="gpt-5-mini")
        parser.add_argument("--second-pass-reasoning-effort", default="medium")
        parser.add_argument("--prompt-version", default=PROMPT_VERSION)
        parser.add_argument("--coordinator-label", default="guest-extraction-batch-backfill")
        parser.add_argument("--poll-interval-seconds", type=int, default=300)
        parser.add_argument(
            "--new-episodes-only",
            action="store_true",
            help="First pass only selects episodes with no successful guest extraction at all.",
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
        parser.add_argument(
            "--output-dir",
            default="data/reports/batches",
            help="Directory for local batch input and output files.",
        )

    def handle(self, *args: object, **options: object) -> None:
        first_pass_batch_size = positive_int(
            options["first_pass_batch_size"],
            "--first-pass-batch-size",
        )
        max_first_pass_batches = nonnegative_int(
            options["max_first_pass_batches"],
            "--max-first-pass-batches",
        )
        poll_interval_seconds = positive_int(
            options["poll_interval_seconds"],
            "--poll-interval-seconds",
        )
        client = OpenAI()
        completed_first_pass_batches = 0

        while max_first_pass_batches == 0 or (
            completed_first_pass_batches < max_first_pass_batches
        ):
            first_pass_run = self.get_or_submit_first_pass_run(
                client=client,
                batch_size=first_pass_batch_size,
                options=options,
            )
            if first_pass_run is None:
                self.stdout.write(self.style.SUCCESS("No remaining first-pass episodes."))
                return

            if not self.wait_and_sync_run(
                client=client,
                run=first_pass_run,
                poll_interval_seconds=poll_interval_seconds,
            ):
                return
            completed_first_pass_batches += 1

            second_pass_run = self.get_or_submit_second_pass_run(
                client=client,
                first_pass_run=first_pass_run,
                options=options,
            )
            if second_pass_run is not None and not self.wait_and_sync_run(
                client=client,
                run=second_pass_run,
                poll_interval_seconds=poll_interval_seconds,
            ):
                return

        self.stdout.write(
            self.style.SUCCESS(
                f"Completed {completed_first_pass_batches} first-pass batch(es)."
            )
        )

    def get_or_submit_first_pass_run(
        self,
        *,
        client: OpenAI,
        batch_size: int,
        options: dict[str, object],
    ) -> ExtractionRun | None:
        existing = self.find_running_run(
            coordinator_label=str(options["coordinator_label"]),
            phase="first_pass",
            model=str(options["first_pass_model"]),
            prompt_version=str(options["prompt_version"]),
        )
        if existing:
            self.stdout.write(f"Resuming first-pass run {existing.id}.")
            return existing

        episodes = select_episodes(
            episode_ids=[],
            limit=batch_size,
            model=str(options["first_pass_model"]),
            prompt_version=str(options["prompt_version"]),
            force=False,
            new_episodes_only=bool(options["new_episodes_only"]),
        )
        if not episodes:
            return None

        return self.submit_batch(
            client=client,
            episodes=episodes,
            model=str(options["first_pass_model"]),
            reasoning_effort=str(options["first_pass_reasoning_effort"]),
            prompt_version=str(options["prompt_version"]),
            output_dir=Path(str(options["output_dir"])),
            metadata={
                "run_label": str(options["coordinator_label"]),
                "coordinator_label": str(options["coordinator_label"]),
                "phase": "first_pass",
            },
        )

    def get_or_submit_second_pass_run(
        self,
        *,
        client: OpenAI,
        first_pass_run: ExtractionRun,
        options: dict[str, object],
    ) -> ExtractionRun | None:
        existing = self.find_running_run(
            coordinator_label=str(options["coordinator_label"]),
            phase="second_pass",
            model=str(options["second_pass_model"]),
            prompt_version=str(options["prompt_version"]),
            first_pass_run_id=first_pass_run.id,
        )
        if existing:
            self.stdout.write(f"Resuming second-pass run {existing.id}.")
            return existing

        episodes = select_second_pass_review_episodes(
            first_pass_run=first_pass_run,
            first_pass_model=str(options["first_pass_model"]),
            second_pass_model=str(options["second_pass_model"]),
            prompt_version=str(options["prompt_version"]),
            review_min_confidence=float(options["review_min_confidence"]),
            review_max_confidence=float(options["review_max_confidence"]),
            require_no_high_confidence=not options["review_allow_high_confidence"],
        )
        if not episodes:
            self.stdout.write(
                f"No second-pass review episodes for first-pass run {first_pass_run.id}."
            )
            return None

        return self.submit_batch(
            client=client,
            episodes=episodes,
            model=str(options["second_pass_model"]),
            reasoning_effort=str(options["second_pass_reasoning_effort"]),
            prompt_version=str(options["prompt_version"]),
            output_dir=Path(str(options["output_dir"])),
            metadata={
                "run_label": str(options["coordinator_label"]),
                "coordinator_label": str(options["coordinator_label"]),
                "phase": "second_pass",
                "review_band_run_id": first_pass_run.id,
            },
        )

    def submit_batch(
        self,
        *,
        client: OpenAI,
        episodes: list[Episode],
        model: str,
        reasoning_effort: str,
        prompt_version: str,
        output_dir: Path,
        metadata: dict[str, object],
    ) -> ExtractionRun:
        timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        jsonl_path = output_dir / f"guest_extraction_{model}_{timestamp}.jsonl"
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
                    "run_label": str(metadata["run_label"]),
                    "prompt_version": prompt_version,
                    "phase": str(metadata["phase"]),
                },
            )
        except Exception as exc:
            raise CommandError(f"OpenAI batch submission failed: {exc}") from exc

        run = ExtractionRun.objects.create(
            model=model,
            provider="openai-batch",
            prompt_version=prompt_version,
            episodes_requested=len(episodes),
            metadata={
                **metadata,
                "batch_id": batch.id,
                "input_file_id": uploaded_file.id,
                "input_jsonl_path": str(jsonl_path),
                "endpoint": BATCH_ENDPOINT,
                "reasoning_effort": reasoning_effort,
            },
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Submitted {metadata['phase']} run {run.id}: batch {batch.id}, "
                f"{len(episodes)} episodes."
            )
        )
        return run

    def wait_and_sync_run(
        self,
        *,
        client: OpenAI,
        run: ExtractionRun,
        poll_interval_seconds: int,
    ) -> bool:
        while run.status == ExtractionRun.Status.RUNNING:
            batch = client.batches.retrieve(str(run.metadata["batch_id"]))
            counts = getattr(batch, "request_counts", None)
            self.stdout.write(
                f"{timezone.now().isoformat()} - Run {run.id} batch {batch.id}: "
                f"{batch.status}; requests={counts}."
            )
            if batch.status == "completed":
                self.sync_completed_batch(client=client, run=run, batch=batch)
                run.refresh_from_db()
                return True
            if batch.status in {"failed", "expired", "cancelled"}:
                self.mark_failed(run=run, batch=batch)
                return False
            self.stdout.write(
                f"Sleeping {poll_interval_seconds}s before checking run {run.id} again."
            )
            time.sleep(poll_interval_seconds)
        return run.status in {ExtractionRun.Status.SUCCEEDED, ExtractionRun.Status.PARTIAL}

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
            error_path.write_text(download_file_text(client, batch.error_file_id))
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
        self.stdout.write(self.style.ERROR(f"Run {run.id} failed: batch {batch.status}."))
        if errors:
            for error in errors.data:
                self.stdout.write(self.style.ERROR(f"{error.code}: {error.message}"))

    def find_running_run(
        self,
        *,
        coordinator_label: str,
        phase: str,
        model: str,
        prompt_version: str,
        first_pass_run_id: int | None = None,
    ) -> ExtractionRun | None:
        queryset = ExtractionRun.objects.filter(
            provider="openai-batch",
            status=ExtractionRun.Status.RUNNING,
            model=model,
            prompt_version=prompt_version,
            metadata__coordinator_label=coordinator_label,
            metadata__phase=phase,
        )
        if first_pass_run_id is not None:
            queryset = queryset.filter(metadata__review_band_run_id=first_pass_run_id)
        return queryset.order_by("started_at").first()
