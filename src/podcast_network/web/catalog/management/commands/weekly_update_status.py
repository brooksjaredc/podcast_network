from __future__ import annotations

from django.core.management.base import BaseCommand, CommandParser
from django.db.models import Count, Sum

from podcast_network.web.catalog.models import (
    EpisodeGuestExtraction,
    ExtractionRun,
    FutureLinkPredictionRun,
    FutureLinkWeeklyAuditRun,
    NetworkEvolutionRun,
    NetworkMetricRun,
    PipelineRun,
    ScrapeRun,
)


class Command(BaseCommand):
    help = "Summarize auditable status for a weekly update run label."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--run-label",
            required=True,
            help="Weekly update run label, usually weekly-update-<workflow-execution-id>.",
        )

    def handle(self, *args: object, **options: object) -> None:
        run_label = str(options["run_label"])
        self.stdout.write(self.style.MIGRATE_HEADING(f"Weekly update status: {run_label}"))
        self.print_pipeline_status(run_label)
        self.print_scrape_status(run_label)
        self.print_extraction_status(run_label)
        self.print_processing_status(run_label)
        self.print_prediction_status(run_label)
        self.print_metric_status(run_label)

    def print_pipeline_status(self, run_label: str) -> None:
        self.stdout.write(self.style.MIGRATE_HEADING("Pipeline"))
        run = PipelineRun.objects.filter(run_label=run_label).order_by("-started_at").first()
        if run is None:
            self.stdout.write("No pipeline run found.")
            return
        self.stdout.write(
            f"- PipelineRun {run.id}: {run.status}, phase={run.phase}, "
            f"started={run.started_at}, finished={run.finished_at}"
        )
        for step in run.steps.order_by("sequence"):
            progress = format_progress_metadata(step.metadata)
            suffix = f", progress={progress}" if progress else ""
            self.stdout.write(
                f"  - {step.sequence}. {step.command}: {step.status}, "
                f"elapsed={step.elapsed_seconds}{suffix}"
            )

    def print_scrape_status(self, run_label: str) -> None:
        runs = ScrapeRun.objects.filter(run_label=run_label).order_by("-started_at")
        self.stdout.write(self.style.MIGRATE_HEADING("Scrape"))
        if not runs.exists():
            self.stdout.write("No scrape runs found.")
            return
        for run in runs:
            self.stdout.write(
                f"- ScrapeRun {run.id}: {run.status}, requested={run.feeds_requested}, "
                f"succeeded={run.feeds_succeeded}, failed={run.feeds_failed}, "
                f"started={run.started_at}, finished={run.finished_at}"
            )

    def print_extraction_status(self, run_label: str) -> None:
        runs = ExtractionRun.objects.filter(
            provider="openai-batch",
            metadata__coordinator_label=run_label,
        ).order_by("started_at")
        self.stdout.write(self.style.MIGRATE_HEADING("LLM extraction"))
        if not runs.exists():
            self.stdout.write("No extraction runs found.")
            return
        totals = runs.aggregate(
            requested=Sum("episodes_requested"),
            succeeded=Sum("episodes_succeeded"),
            failed=Sum("episodes_failed"),
            input_tokens=Sum("input_tokens"),
            output_tokens=Sum("output_tokens"),
        )
        self.stdout.write(
            "Totals: "
            f"requested={totals['requested'] or 0}, "
            f"succeeded={totals['succeeded'] or 0}, "
            f"failed={totals['failed'] or 0}, "
            f"input_tokens={totals['input_tokens'] or 0}, "
            f"output_tokens={totals['output_tokens'] or 0}"
        )
        by_model = (
            runs.values("model", "prompt_version", "status")
            .annotate(
                runs=Count("id"),
                requested=Sum("episodes_requested"),
                succeeded=Sum("episodes_succeeded"),
                failed=Sum("episodes_failed"),
            )
            .order_by("prompt_version", "model", "status")
        )
        for row in by_model:
            self.stdout.write(
                f"- {row['prompt_version']} {row['model']} {row['status']}: "
                f"runs={row['runs']}, requested={row['requested'] or 0}, "
                f"succeeded={row['succeeded'] or 0}, failed={row['failed'] or 0}"
            )

    def print_processing_status(self, run_label: str) -> None:
        extractions = EpisodeGuestExtraction.objects.filter(
            extraction_run__metadata__coordinator_label=run_label,
            status=EpisodeGuestExtraction.Status.SUCCEEDED,
        )
        self.stdout.write(self.style.MIGRATE_HEADING("Materialization scope"))
        self.stdout.write(
            f"- Successful episode extractions available for materialization: "
            f"{extractions.count()}"
        )

    def print_prediction_status(self, run_label: str) -> None:
        self.stdout.write(self.style.MIGRATE_HEADING("Future-link predictions"))
        for run in FutureLinkWeeklyAuditRun.objects.filter(run_id=run_label):
            self.stdout.write(
                f"- Weekly audit: new_links={run.new_link_count}, "
                f"scored={run.scored_link_count}, candidates={run.candidate_eligible_count}, "
                f"created={run.created_at}"
            )
        for run in FutureLinkPredictionRun.objects.filter(run_id=run_label):
            self.stdout.write(
                f"- Current predictions: candidates={run.candidate_count}, "
                f"rows_written={run.rows_written}, podcasts={run.scored_podcast_count}, "
                f"created={run.created_at}"
            )

    def print_metric_status(self, run_label: str) -> None:
        self.stdout.write(self.style.MIGRATE_HEADING("Network metrics"))
        run = (
            NetworkMetricRun.objects.filter(metadata__run_label=run_label)
            .order_by("-started_at")
            .first()
        )
        if run is None:
            self.stdout.write("No network metric run found for this label.")
        else:
            self.stdout.write(
                f"- NetworkMetricRun {run.id}: {run.status}, "
                f"person_nodes={run.person_nodes}, person_edges={run.person_edges}, "
                f"podcast_nodes={run.podcast_nodes}, podcast_edges={run.podcast_edges}, "
                f"finished={run.finished_at}"
            )
        evolution_run = (
            NetworkEvolutionRun.objects.filter(metadata__run_label=run_label)
            .order_by("-started_at")
            .first()
        )
        if evolution_run is None:
            self.stdout.write("- No network evolution run found for this label.")
        else:
            self.stdout.write(
                f"- NetworkEvolutionRun {evolution_run.id}: {evolution_run.status}, "
                f"weeks={evolution_run.weeks_calculated}/{evolution_run.weeks_requested}, "
                f"finished={evolution_run.finished_at}"
            )


def format_progress_metadata(metadata: dict[str, object]) -> str:
    if not metadata:
        return ""
    preferred_keys = [
        "processed",
        "total",
        "succeeded",
        "failed",
        "batch_status",
        "candidate_count",
        "rows_written",
    ]
    parts = [
        f"{key}={metadata[key]}"
        for key in preferred_keys
        if key in metadata and metadata[key] not in {"", None}
    ]
    return ", ".join(parts)
