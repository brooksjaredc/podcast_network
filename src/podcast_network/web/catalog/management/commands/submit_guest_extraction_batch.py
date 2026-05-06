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
    select_second_pass_review_episodes,
)
from podcast_network.web.catalog.management.commands.extract_guests import select_episodes
from podcast_network.web.catalog.models import ExtractionRun


class Command(BaseCommand):
    help = "Submit an OpenAI Batch API guest extraction job."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--batch-size", type=int, default=5000)
        parser.add_argument("--model", default=DEFAULT_EXTRACTION_MODEL)
        parser.add_argument("--prompt-version", default=PROMPT_VERSION)
        parser.add_argument("--reasoning-effort", default="minimal")
        parser.add_argument("--run-label", default="guest-extraction-batch")
        parser.add_argument(
            "--review-band-run-id",
            type=int,
            default=0,
            help="Submit a second-pass batch from review-band episodes in this first-pass run.",
        )
        parser.add_argument("--review-source-model", default=DEFAULT_EXTRACTION_MODEL)
        parser.add_argument("--review-min-confidence", type=float, default=0.75)
        parser.add_argument("--review-max-confidence", type=float, default=0.90)
        parser.add_argument(
            "--review-allow-high-confidence",
            action="store_true",
            help=(
                "Include review-band episodes even when source run has a "
                "high-confidence candidate."
            ),
        )
        parser.add_argument(
            "--output-dir",
            default="data/reports/batches",
            help="Directory for local batch input and output files.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Write JSONL locally but do not upload or create an OpenAI batch.",
        )

    def handle(self, *args: object, **options: object) -> None:
        batch_size = positive_int(options["batch_size"], "--batch-size")
        model = str(options["model"])
        prompt_version = str(options["prompt_version"])
        reasoning_effort = str(options["reasoning_effort"])
        timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        output_dir = Path(str(options["output_dir"]))
        jsonl_path = output_dir / f"guest_extraction_{model}_{timestamp}.jsonl"

        review_band_run_id = int(options["review_band_run_id"])
        if review_band_run_id:
            first_pass_run = ExtractionRun.objects.get(id=review_band_run_id)
            episodes = select_second_pass_review_episodes(
                first_pass_run=first_pass_run,
                first_pass_model=str(options["review_source_model"]),
                second_pass_model=model,
                prompt_version=prompt_version,
                review_min_confidence=float(options["review_min_confidence"]),
                review_max_confidence=float(options["review_max_confidence"]),
                require_no_high_confidence=not options["review_allow_high_confidence"],
            )[:batch_size]
        else:
            episodes = select_episodes(
                episode_ids=[],
                limit=batch_size,
                model=model,
                prompt_version=prompt_version,
                force=False,
            )
        if not episodes:
            self.stdout.write(self.style.WARNING("No episodes selected for batch submission."))
            return

        write_batch_jsonl(
            episodes,
            model=model,
            reasoning_effort=reasoning_effort,
            path=jsonl_path,
        )
        if options["dry_run"]:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Wrote {len(episodes)} batch requests to {jsonl_path}; dry run only."
                )
            )
            return

        client = OpenAI()
        try:
            with jsonl_path.open("rb") as jsonl_file:
                uploaded_file = client.files.create(file=jsonl_file, purpose="batch")
            batch = client.batches.create(
                input_file_id=uploaded_file.id,
                endpoint=BATCH_ENDPOINT,
                completion_window="24h",
                metadata={
                    "run_label": str(options["run_label"]),
                    "prompt_version": prompt_version,
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
                "run_label": str(options["run_label"]),
                "batch_id": batch.id,
                "input_file_id": uploaded_file.id,
                "input_jsonl_path": str(jsonl_path),
                "endpoint": BATCH_ENDPOINT,
                "reasoning_effort": reasoning_effort,
                "review_band_run_id": review_band_run_id or "",
            },
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Submitted OpenAI batch {batch.id} for run {run.id} "
                f"with {len(episodes)} episodes. Input: {jsonl_path}"
            )
        )
