from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError, CommandParser
from openai import OpenAI

from podcast_network.web.catalog.models import ExtractionRun


class Command(BaseCommand):
    help = "Check an OpenAI Batch API guest extraction run."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--run-id", type=int, required=True)

    def handle(self, *args: object, **options: object) -> None:
        run = ExtractionRun.objects.get(id=int(options["run_id"]))
        batch_id = run.metadata.get("batch_id")
        if not batch_id:
            raise CommandError(f"ExtractionRun {run.id} has no batch_id metadata.")

        batch = OpenAI().batches.retrieve(str(batch_id))
        counts = getattr(batch, "request_counts", None)
        self.stdout.write(
            self.style.SUCCESS(
                f"Run {run.id} batch {batch.id}: {batch.status}. "
                f"requests={counts if counts else 'unknown'} "
                f"output_file_id={batch.output_file_id or ''} "
                f"error_file_id={batch.error_file_id or ''}"
            )
        )
