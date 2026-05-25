from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandParser
from django.db import close_old_connections

from podcast_network.extraction.openai_client import DEFAULT_EXTRACTION_MODEL
from podcast_network.extraction.prompt import PROMPT_VERSION
from podcast_network.web.catalog.management.commands.promote_frequent_guests_to_cohosts import (
    DEFAULT_COHOST_EPISODE_SHARE,
    DEFAULT_COHOST_EPISODE_THRESHOLD,
)
from podcast_network.web.catalog.models import ExtractionRun
from podcast_network.web.explorer.services import database_six_degrees_graph


@dataclass(frozen=True)
class PipelineStep:
    name: str
    command: str
    options: dict[str, object]


TODO_NOTES = (
    "Add post-extraction quality reports for topic-only false positives.",
    "Add scheduled host/co-host extraction refresh for newly discovered podcasts.",
    "Add single-name resolution once the cheaper/contextual strategy is settled.",
    "Add entity-resolution active-learning sampling for new uncertain pairs.",
)


class Command(BaseCommand):
    help = (
        "Coordinate the weekly scrape, guest extraction, processing, ER, "
        "graph refresh, and future-link predictions."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--phase",
            choices=[
                "all",
                "scrape",
                "llm",
                "processing-er",
                "metrics",
                "predictions",
                "plots",
            ],
            default="all",
            help=(
                "Run one phase of the weekly update. Use 'all' for the legacy "
                "single-process coordinator."
            ),
        )
        parser.add_argument("--feed-timeout", type=int, default=20)
        parser.add_argument("--feed-concurrency", type=int, default=8)
        parser.add_argument("--feed-progress-every", type=int, default=50)
        parser.add_argument("--max-feed-mb", type=float, default=50.0)
        parser.add_argument("--max-episodes-per-feed", type=int, default=500)
        parser.add_argument(
            "--raw-snapshot-storage",
            choices=["local", "none"],
            default="none",
            help="Use 'none' for Cloud Run jobs so RSS XML is not written to the image FS.",
        )
        parser.add_argument("--include-inactive-feeds", action="store_true")
        parser.add_argument("--first-pass-batch-size", type=int, default=1000)
        parser.add_argument(
            "--max-first-pass-batches",
            type=int,
            default=0,
            help="Maximum first-pass batches to complete. Default 0 runs until exhausted.",
        )
        parser.add_argument("--first-pass-model", default=DEFAULT_EXTRACTION_MODEL)
        parser.add_argument("--first-pass-reasoning-effort", default="low")
        parser.add_argument("--second-pass-model", default="gpt-5-mini")
        parser.add_argument("--second-pass-reasoning-effort", default="medium")
        parser.add_argument("--prompt-version", default=PROMPT_VERSION)
        parser.add_argument("--coordinator-label", default="")
        parser.add_argument(
            "--llm-output-dir",
            default="/tmp/podcast-network-batches",
            help="Temporary OpenAI batch input/output directory for Cloud Run.",
        )
        parser.add_argument("--poll-interval-seconds", type=int, default=300)
        parser.add_argument("--review-min-confidence", type=float, default=0.75)
        parser.add_argument("--review-max-confidence", type=float, default=0.90)
        parser.add_argument("--min-guest-confidence", type=float, default=0.90)
        parser.add_argument(
            "--cohost-threshold",
            type=int,
            default=DEFAULT_COHOST_EPISODE_THRESHOLD,
        )
        parser.add_argument(
            "--cohost-episode-share-threshold",
            type=float,
            default=DEFAULT_COHOST_EPISODE_SHARE,
        )
        parser.add_argument("--entity-limit-pairs", type=int, default=20000)
        parser.add_argument("--entity-min-score", type=float, default=0.5)
        parser.add_argument("--entity-min-observations", type=int, default=1)
        parser.add_argument("--evolution-max-weeks", type=int, default=1)
        parser.add_argument("--evolution-person-metric-limit", type=int, default=100)
        parser.add_argument("--evolution-betweenness-sample-size", type=int, default=200)
        parser.add_argument("--evolution-closeness-sample-size", type=int, default=200)
        parser.add_argument(
            "--future-link-model-path",
            default="data/models/future_link_exact_lr_unweighted_onecut.joblib",
        )
        parser.add_argument("--future-link-gcs-model-uri", default="")
        parser.add_argument("--future-link-top-n", type=int, default=1000)
        parser.add_argument("--future-link-batch-size", type=int, default=200000)
        parser.add_argument("--future-link-max-degree", type=int, default=3)
        parser.add_argument("--plot-output-dir", default="static/plots")
        parser.add_argument("--plot-gcs-output-uri", default="")
        parser.add_argument(
            "--reprocess-current-prompt",
            action="store_true",
            help=(
                "Allow first-pass extraction for episodes lacking this prompt/model. "
                "Default only extracts episodes with no successful guest extraction at all."
            ),
        )
        parser.add_argument("--skip-scrape", action="store_true")
        parser.add_argument("--skip-llm", action="store_true")
        parser.add_argument("--skip-processing", action="store_true")
        parser.add_argument("--skip-entity-resolution", action="store_true")
        parser.add_argument("--skip-network-metrics", action="store_true")
        parser.add_argument("--skip-network-evolution", action="store_true")
        parser.add_argument("--skip-future-link-predictions", action="store_true")
        parser.add_argument("--skip-static-plots", action="store_true")
        parser.add_argument("--skip-graph-warm", action="store_true")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print the coordinated command plan without executing it.",
        )

    def handle(self, *args: object, **options: object) -> None:
        steps = build_pipeline_steps(options)
        if options["dry_run"]:
            self.print_plan(steps)
            self.print_todos()
            return

        for step in steps:
            close_old_connections()
            started = time.monotonic()
            self.stdout.write(self.style.MIGRATE_HEADING(f"== {step.name} =="))
            call_command(step.command, **step.options)
            elapsed = time.monotonic() - started
            self.stdout.write(self.style.SUCCESS(f"Completed {step.name} in {elapsed:.1f}s."))
            close_old_connections()

        if should_warm_graph(options):
            close_old_connections()
            started = time.monotonic()
            self.stdout.write(self.style.MIGRATE_HEADING("== Warm DB graph =="))
            database_six_degrees_graph.cache_clear()
            graph = database_six_degrees_graph()
            self.stdout.write(
                self.style.SUCCESS(
                    f"Loaded graph with {len(graph.names)} names and "
                    f"{len(graph.podcast_ids)} podcasts."
                )
            )
            self.stdout.write(
                self.style.SUCCESS(f"Completed Warm DB graph in {time.monotonic() - started:.1f}s.")
            )
            close_old_connections()

        self.print_todos()
        self.stdout.write(self.style.SUCCESS("Weekly update pipeline complete."))

    def print_plan(self, steps: list[PipelineStep]) -> None:
        self.stdout.write(self.style.MIGRATE_HEADING("Weekly update dry-run plan"))
        for step in steps:
            options = " ".join(f"{key}={value!r}" for key, value in sorted(step.options.items()))
            self.stdout.write(f"- {step.name}: call_command({step.command!r}, {options})")

    def print_todos(self) -> None:
        self.stdout.write(self.style.MIGRATE_HEADING("TODO hooks for upcoming work"))
        for note in TODO_NOTES:
            self.stdout.write(f"- TODO: {note}")


def build_pipeline_steps(options: dict[str, object]) -> list[PipelineStep]:
    steps: list[PipelineStep] = []
    phase = str(options.get("phase", "all"))
    coordinator_label = resolve_coordinator_label(options)
    if phase in {"all", "scrape"} and not options["skip_scrape"]:
        steps.append(
            PipelineStep(
                name="Scrape RSS feeds",
                command="ingest_feeds",
                options={
                    "timeout": int(options["feed_timeout"]),
                    "concurrency": int(options["feed_concurrency"]),
                    "progress_every": int(options["feed_progress_every"]),
                    "max_feed_mb": float(options["max_feed_mb"]),
                    "max_episodes_per_feed": int(options["max_episodes_per_feed"]),
                    "raw_snapshot_storage": str(options["raw_snapshot_storage"]),
                    "inactive": bool(options["include_inactive_feeds"]),
                    "run_label": coordinator_label,
                },
            )
        )
    if phase in {"all", "llm"} and not options["skip_llm"]:
        steps.append(
            PipelineStep(
                name="Run OpenAI Batch API guest extraction",
                command="run_guest_extraction_batch_backfill",
                options={
                    "first_pass_batch_size": int(options["first_pass_batch_size"]),
                    "max_first_pass_batches": int(options["max_first_pass_batches"]),
                    "first_pass_model": str(options["first_pass_model"]),
                    "first_pass_reasoning_effort": str(options["first_pass_reasoning_effort"]),
                    "second_pass_model": str(options["second_pass_model"]),
                    "second_pass_reasoning_effort": str(options["second_pass_reasoning_effort"]),
                    "prompt_version": str(options["prompt_version"]),
                    "coordinator_label": coordinator_label,
                    "poll_interval_seconds": int(options["poll_interval_seconds"]),
                    "review_min_confidence": float(options["review_min_confidence"]),
                    "review_max_confidence": float(options["review_max_confidence"]),
                    "new_episodes_only": not bool(options["reprocess_current_prompt"]),
                    "output_dir": str(options["llm_output_dir"]),
                },
            )
        )
    if phase in {"all", "processing-er"} and not options["skip_processing"]:
        steps.extend(
            [
                PipelineStep(
                    name="Materialize guest appearances",
                    command="sync_guest_appearances",
                    options={
                        "prompt_version": str(options["prompt_version"]),
                        "first_pass_model": str(options["first_pass_model"]),
                        "second_pass_model": str(options["second_pass_model"]),
                        "min_confidence": float(options["min_guest_confidence"]),
                        "extraction_run_label": coordinator_label,
                    },
                ),
                PipelineStep(
                    name="Promote frequent guests to co-hosts",
                    command="promote_frequent_guests_to_cohosts",
                    options={
                        "threshold": int(options["cohost_threshold"]),
                        "episode_share_threshold": float(options["cohost_episode_share_threshold"]),
                        "clear_existing": True,
                    },
                ),
            ]
        )
    if phase in {"all", "processing-er"} and not options["skip_entity_resolution"]:
        steps.append(
            PipelineStep(
                name="Refresh person entity resolution",
                command="refresh_person_entity_resolution",
                options={
                    "limit_pairs": int(options["entity_limit_pairs"]),
                    "min_score": float(options["entity_min_score"]),
                    "min_observations": int(options["entity_min_observations"]),
                },
            )
        )
    if phase in {"all", "metrics"} and not options["skip_network_metrics"]:
        steps.append(
            PipelineStep(
                name="Calculate network metrics",
                command="calculate_network_metrics",
                options={"run_label": coordinator_label},
            )
        )
    if phase in {"all", "metrics"} and not options["skip_network_evolution"]:
        steps.append(
            PipelineStep(
                name="Calculate incremental network evolution",
                command="calculate_network_evolution",
                options={
                    "max_weeks": int(options["evolution_max_weeks"]),
                    "person_metric_limit": int(options["evolution_person_metric_limit"]),
                    "betweenness_sample_size": int(options["evolution_betweenness_sample_size"]),
                    "closeness_sample_size": int(options["evolution_closeness_sample_size"]),
                    "run_label": coordinator_label,
                },
            )
        )
    if phase in {"all", "predictions"} and not options["skip_future_link_predictions"]:
        model_options = future_link_model_options(options)
        run_id = coordinator_label
        steps.extend(
            [
                PipelineStep(
                    name="Audit newly published future links",
                    command="audit_future_link_weekly_new_links",
                    options={
                        **model_options,
                        "run_id": run_id,
                        "max_degree": int(options["future_link_max_degree"]),
                    },
                ),
                PipelineStep(
                    name="Score current future-link predictions",
                    command="score_future_link_predictions",
                    options={
                        **model_options,
                        "run_id": run_id,
                        "top_n": int(options["future_link_top_n"]),
                        "batch_size": int(options["future_link_batch_size"]),
                        "max_degree": int(options["future_link_max_degree"]),
                    },
                ),
            ]
        )
    if phase in {"all", "predictions", "plots"} and not options["skip_static_plots"]:
        steps.append(
            PipelineStep(
                name="Regenerate static plots",
                command="generate_static_plots",
                options={
                    "output_dir": str(options["plot_output_dir"]),
                    "gcs_output_uri": str(options["plot_gcs_output_uri"]),
                },
            )
        )
    return steps


def should_warm_graph(options: dict[str, object]) -> bool:
    return str(options.get("phase", "all")) in {"all", "metrics"} and not bool(
        options["skip_graph_warm"]
    )


def weekly_label() -> str:
    return f"weekly-update-{datetime.now(tz=UTC).strftime('%Y%m%dT%H%M%SZ')}"


def resolve_coordinator_label(options: dict[str, object]) -> str:
    explicit_label = str(options["coordinator_label"])
    if explicit_label:
        return explicit_label
    phase = str(options.get("phase", "all"))
    if phase in {"processing-er", "predictions"}:
        latest_label = latest_extraction_coordinator_label()
        if latest_label:
            return latest_label
    return weekly_label()


def latest_extraction_coordinator_label() -> str:
    rows = (
        ExtractionRun.objects.filter(
            provider="openai-batch",
            status__in=[ExtractionRun.Status.SUCCEEDED, ExtractionRun.Status.PARTIAL],
            metadata__has_key="coordinator_label",
        )
        .order_by("-finished_at", "-started_at")
        .values_list("metadata", flat=True)[:50]
    )
    for metadata in rows:
        label = str(metadata.get("coordinator_label") or "")
        if label:
            return label
    return ""


def future_link_model_options(options: dict[str, object]) -> dict[str, str]:
    model_path = str(options["future_link_model_path"])
    gcs_model_uri = str(options["future_link_gcs_model_uri"])
    if gcs_model_uri:
        model_path = ""
    if not model_path and not gcs_model_uri:
        raise ValueError(
            "Future-link predictions need --future-link-model-path or "
            "--future-link-gcs-model-uri, or use --skip-future-link-predictions."
        )
    return {
        "model_path": model_path,
        "gcs_model_uri": gcs_model_uri,
    }
