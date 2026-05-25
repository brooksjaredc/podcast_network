from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone
from openai import OpenAI

from podcast_network.extraction.pipeline import finalize_extraction_run
from podcast_network.web.catalog.management.commands.sync_guest_extraction_batch import (
    download_file_text,
    sync_output_lines,
    write_batch_artifact,
)
from podcast_network.web.catalog.models import ExtractionRun


class Command(BaseCommand):
    help = "Sync or mark status for multiple OpenAI Batch API guest extraction runs."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--run-label", default="")
        parser.add_argument("--min-run-id", type=int, default=0)
        parser.add_argument("--max-run-id", type=int, default=0)
        parser.add_argument(
            "--include-non-running",
            action="store_true",
            help="Also inspect runs that are already marked succeeded/failed locally.",
        )
        parser.add_argument(
            "--mark-duplicates-from-run-id",
            type=int,
            default=0,
            help=(
                "Mark matching runs at or above this id as failed locally without "
                "downloading outputs. Use only for known duplicate submissions."
            ),
        )

    def handle(self, *args: object, **options: object) -> None:
        queryset = ExtractionRun.objects.filter(provider="openai-batch")
        run_label = str(options["run_label"])
        if run_label:
            queryset = queryset.filter(metadata__run_label=run_label)
        min_run_id = int(options["min_run_id"])
        max_run_id = int(options["max_run_id"])
        if min_run_id:
            queryset = queryset.filter(id__gte=min_run_id)
        if max_run_id:
            queryset = queryset.filter(id__lte=max_run_id)
        if not options["include_non_running"]:
            queryset = queryset.filter(status=ExtractionRun.Status.RUNNING)
        runs = list(queryset.order_by("id"))
        if not runs:
            self.stdout.write(self.style.WARNING("No matching batch runs found."))
            return

        duplicate_from = int(options["mark_duplicates_from_run_id"])
        if duplicate_from:
            count = 0
            for run in runs:
                if run.id < duplicate_from:
                    continue
                run.status = ExtractionRun.Status.FAILED
                run.finished_at = timezone.now()
                run.metadata = {
                    **run.metadata,
                    "batch_status": "duplicate_not_synced",
                    "duplicate_of_earlier_series": True,
                }
                run.save(update_fields=["status", "finished_at", "metadata"])
                count += 1
            self.stdout.write(self.style.SUCCESS(f"Marked {count} duplicate run(s) failed."))
            return

        client = OpenAI()
        synced = 0
        failed = 0
        pending = 0
        for run in runs:
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
            self.style.SUCCESS(
                f"Batch status sync complete: {synced} synced, "
                f"{failed} failed, {pending} pending."
            )
        )

    def sync_completed_batch(self, *, client: OpenAI, run: ExtractionRun, batch) -> None:
        if not batch.output_file_id:
            raise CommandError(f"Batch {batch.id} completed without an output_file_id.")

        output_text = download_file_text(client, batch.output_file_id)
        output_path, output_gcs_uri = write_batch_artifact(
            run=run,
            filename="output.jsonl",
            text=output_text,
        )
        outcomes = sync_output_lines(run=run, output_text=output_text)

        metadata = {
            **run.metadata,
            "output_file_id": batch.output_file_id,
            "output_jsonl_path": str(output_path),
        }
        if output_gcs_uri:
            metadata["output_jsonl_gcs_uri"] = output_gcs_uri
        if batch.error_file_id:
            error_path, error_gcs_uri = write_batch_artifact(
                run=run,
                filename="errors.jsonl",
                text=download_file_text(client, batch.error_file_id),
            )
            metadata["error_file_id"] = batch.error_file_id
            metadata["error_jsonl_path"] = str(error_path)
            if error_gcs_uri:
                metadata["error_jsonl_gcs_uri"] = error_gcs_uri
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
