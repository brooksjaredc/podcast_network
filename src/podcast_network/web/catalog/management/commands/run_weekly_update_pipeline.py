from __future__ import annotations

from dataclasses import dataclass

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandParser

from podcast_network.extraction.openai_client import DEFAULT_EXTRACTION_MODEL
from podcast_network.extraction.prompt import PROMPT_VERSION
from podcast_network.web.catalog.management.commands.promote_frequent_guests_to_cohosts import (
    DEFAULT_COHOST_EPISODE_SHARE,
    DEFAULT_COHOST_EPISODE_THRESHOLD,
)
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
    "Add network metric evolution snapshots and leader-score calculations.",
    "Add optional plot/static artifact regeneration once plots read from Postgres metrics.",
)


class Command(BaseCommand):
    help = "Coordinate the weekly scrape, guest extraction, processing, ER, and graph refresh."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--feed-timeout", type=int, default=20)
        parser.add_argument("--include-inactive-feeds", action="store_true")
        parser.add_argument("--first-pass-batch-size", type=int, default=1000)
        parser.add_argument("--max-first-pass-batches", type=int, default=1)
        parser.add_argument("--first-pass-model", default=DEFAULT_EXTRACTION_MODEL)
        parser.add_argument("--first-pass-reasoning-effort", default="low")
        parser.add_argument("--second-pass-model", default="gpt-5-mini")
        parser.add_argument("--second-pass-reasoning-effort", default="medium")
        parser.add_argument("--prompt-version", default=PROMPT_VERSION)
        parser.add_argument("--coordinator-label", default="weekly-update")
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
            self.stdout.write(self.style.MIGRATE_HEADING(f"== {step.name} =="))
            call_command(step.command, **step.options)

        if not options["skip_graph_warm"]:
            self.stdout.write(self.style.MIGRATE_HEADING("== Warm DB graph =="))
            database_six_degrees_graph.cache_clear()
            graph = database_six_degrees_graph()
            self.stdout.write(
                self.style.SUCCESS(
                    f"Loaded graph with {len(graph.names)} names and "
                    f"{len(graph.podcast_ids)} podcasts."
                )
            )

        self.print_todos()
        self.stdout.write(self.style.SUCCESS("Weekly update pipeline complete."))

    def print_plan(self, steps: list[PipelineStep]) -> None:
        self.stdout.write(self.style.MIGRATE_HEADING("Weekly update dry-run plan"))
        for step in steps:
            options = " ".join(
                f"{key}={value!r}" for key, value in sorted(step.options.items())
            )
            self.stdout.write(f"- {step.name}: call_command({step.command!r}, {options})")

    def print_todos(self) -> None:
        self.stdout.write(self.style.MIGRATE_HEADING("TODO hooks for upcoming work"))
        for note in TODO_NOTES:
            self.stdout.write(f"- TODO: {note}")


def build_pipeline_steps(options: dict[str, object]) -> list[PipelineStep]:
    steps: list[PipelineStep] = []
    if not options["skip_scrape"]:
        steps.append(
            PipelineStep(
                name="Scrape RSS feeds",
                command="ingest_feeds",
                options={
                    "timeout": int(options["feed_timeout"]),
                    "inactive": bool(options["include_inactive_feeds"]),
                },
            )
        )
    if not options["skip_llm"]:
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
                    "coordinator_label": str(options["coordinator_label"]),
                    "poll_interval_seconds": int(options["poll_interval_seconds"]),
                    "review_min_confidence": float(options["review_min_confidence"]),
                    "review_max_confidence": float(options["review_max_confidence"]),
                    "new_episodes_only": not bool(options["reprocess_current_prompt"]),
                },
            )
        )
    if not options["skip_processing"]:
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
                    },
                ),
                PipelineStep(
                    name="Promote frequent guests to co-hosts",
                    command="promote_frequent_guests_to_cohosts",
                    options={
                        "threshold": int(options["cohost_threshold"]),
                        "episode_share_threshold": float(
                            options["cohost_episode_share_threshold"]
                        ),
                        "clear_existing": True,
                    },
                ),
            ]
        )
    if not options["skip_entity_resolution"]:
        steps.append(
            PipelineStep(
                name="Refresh person entity resolution",
                command="refresh_person_entity_resolution",
                options={"limit_pairs": int(options["entity_limit_pairs"])},
            )
        )
    if not options["skip_network_metrics"]:
        steps.append(
            PipelineStep(
                name="Calculate network metrics",
                command="calculate_network_metrics",
                options={},
            )
        )
    return steps
