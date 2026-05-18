from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError, CommandParser
from openai import OpenAI

from podcast_network.extraction.batch import BATCH_ENDPOINT, write_batch_jsonl
from podcast_network.extraction.openai_client import DEFAULT_EXTRACTION_MODEL
from podcast_network.extraction.prompt import PROMPT_VERSION
from podcast_network.web.catalog.management.commands.backfill_guest_extractions import (
    positive_int,
)
from podcast_network.web.catalog.management.commands.extract_guests import select_episodes
from podcast_network.web.catalog.models import Episode, ExtractionRun


class Command(BaseCommand):
    help = "Submit many non-overlapping OpenAI Batch API guest extraction jobs."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--batch-size", type=int, default=1000)
        parser.add_argument("--max-batches", type=int, default=1)
        parser.add_argument(
            "--skip-episodes",
            type=int,
            default=0,
            help=(
                "Skip this many selected eligible episodes before chunking. "
                "Useful when resuming a partially submitted series."
            ),
        )
        parser.add_argument("--openai-timeout-seconds", type=float, default=60.0)
        parser.add_argument("--model", default=DEFAULT_EXTRACTION_MODEL)
        parser.add_argument("--prompt-version", default=PROMPT_VERSION)
        parser.add_argument("--reasoning-effort", default="minimal")
        parser.add_argument("--run-label", default="guest-extraction-batch-series")
        parser.add_argument(
            "--new-episodes-only",
            action="store_true",
            help="Only select episodes with no successful guest extraction at all.",
        )
        parser.add_argument(
            "--output-dir",
            default="/tmp/podcast-network-batches",
            help="Directory for temporary batch input JSONL files.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Write JSONL files locally but do not upload or create OpenAI batches.",
        )

    def handle(self, *args: object, **options: object) -> None:
        batch_size = positive_int(options["batch_size"], "--batch-size")
        max_batches = positive_int(options["max_batches"], "--max-batches")
        skip_episodes = int(options["skip_episodes"])
        if skip_episodes < 0:
            raise CommandError("--skip-episodes cannot be negative.")
        openai_timeout_seconds = float(options["openai_timeout_seconds"])
        if openai_timeout_seconds <= 0:
            raise CommandError("--openai-timeout-seconds must be positive.")
        model = str(options["model"])
        prompt_version = str(options["prompt_version"])
        reasoning_effort = str(options["reasoning_effort"])
        output_dir = Path(str(options["output_dir"]))
        limit = skip_episodes + batch_size * max_batches

        selected_episodes = select_episodes(
            episode_ids=[],
            limit=limit,
            model=model,
            prompt_version=prompt_version,
            force=False,
            new_episodes_only=bool(options["new_episodes_only"]),
        )
        episodes = selected_episodes[skip_episodes:]
        if not episodes:
            self.stdout.write(self.style.WARNING("No episodes selected for batch submission."))
            return

        chunks = list(chunked(episodes, batch_size))
        self.stdout.write(
            f"Selected {len(episodes)} episodes for {len(chunks)} batch(es) "
            f"of up to {batch_size} after skipping {skip_episodes}."
        )
        client = (
            None
            if options["dry_run"]
            else OpenAI(timeout=openai_timeout_seconds, max_retries=2)
        )

        submitted = 0
        for index, chunk in enumerate(chunks, start=1):
            run = self.submit_chunk(
                client=client,
                episodes=chunk,
                batch_index=index,
                batch_count=len(chunks),
                model=model,
                prompt_version=prompt_version,
                reasoning_effort=reasoning_effort,
                run_label=str(options["run_label"]),
                output_dir=output_dir,
                dry_run=bool(options["dry_run"]),
            )
            if run is not None:
                submitted += 1

        if options["dry_run"]:
            self.stdout.write(self.style.SUCCESS(f"Prepared {len(chunks)} dry-run batch(es)."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Submitted {submitted} batch(es)."))

    def submit_chunk(
        self,
        *,
        client: OpenAI | None,
        episodes: list[Episode],
        batch_index: int,
        batch_count: int,
        model: str,
        prompt_version: str,
        reasoning_effort: str,
        run_label: str,
        output_dir: Path,
        dry_run: bool,
    ) -> ExtractionRun | None:
        timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        jsonl_path = (
            output_dir
            / f"guest_extraction_{model}_{timestamp}_batch_{batch_index:04d}.jsonl"
        )
        write_batch_jsonl(
            episodes,
            model=model,
            reasoning_effort=reasoning_effort,
            path=jsonl_path,
        )
        if dry_run:
            self.stdout.write(
                f"Prepared batch {batch_index}/{batch_count}: "
                f"{len(episodes)} episodes at {jsonl_path}."
            )
            return None
        if client is None:
            raise CommandError("OpenAI client was not initialized.")

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
                    "phase": "first_pass",
                    "series_batch_index": str(batch_index),
                    "series_batch_count": str(batch_count),
                },
            )
        except Exception as exc:
            raise CommandError(
                f"OpenAI batch submission failed for chunk {batch_index}: {exc}"
            ) from exc

        run = ExtractionRun.objects.create(
            model=model,
            provider="openai-batch",
            prompt_version=prompt_version,
            episodes_requested=len(episodes),
            metadata={
                "run_label": run_label,
                "coordinator_label": run_label,
                "phase": "first_pass",
                "batch_id": batch.id,
                "input_file_id": uploaded_file.id,
                "input_jsonl_path": str(jsonl_path),
                "endpoint": BATCH_ENDPOINT,
                "reasoning_effort": reasoning_effort,
                "series_batch_index": batch_index,
                "series_batch_count": batch_count,
            },
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Submitted batch {batch_index}/{batch_count}: run {run.id}, "
                f"batch {batch.id}, {len(episodes)} episodes."
            )
        )
        return run


def chunked[T](items: list[T], size: int) -> list[list[T]]:
    return [items[index : index + size] for index in range(0, len(items), size)]
