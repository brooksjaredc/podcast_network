from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand, CommandParser

from podcast_network.network_evolution import (
    DEFAULT_BETWEENNESS_SAMPLE_SIZE,
    DEFAULT_CLOSENESS_SAMPLE_SIZE,
    calculate_network_evolution,
    missing_evolution_weeks,
    reset_network_evolution_tables,
)


class Command(BaseCommand):
    help = "Calculate incremental weekly network evolution snapshots."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--bootstrap",
            action="store_true",
            help="Start from the first episode week when no evolution snapshots exist.",
        )
        parser.add_argument(
            "--recompute",
            action="store_true",
            help="Replace snapshots for the selected weeks.",
        )
        parser.add_argument("--start-week", type=parse_date)
        parser.add_argument("--through-week", type=parse_date)
        parser.add_argument("--max-weeks", type=int)
        parser.add_argument("--person-metric-limit", type=int, default=100)
        parser.add_argument(
            "--betweenness-sample-size",
            type=int,
            default=DEFAULT_BETWEENNESS_SAMPLE_SIZE,
            help="Approximate betweenness with this many source nodes; 0 means exact.",
        )
        parser.add_argument(
            "--closeness-sample-size",
            type=int,
            default=DEFAULT_CLOSENESS_SAMPLE_SIZE,
            help="Approximate closeness with this many source nodes; 0 means exact.",
        )
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete existing network evolution runs, snapshots, and person metrics first.",
        )
        parser.add_argument(
            "--reset-only",
            action="store_true",
            help="Only delete existing network evolution data, without calculating new weeks.",
        )

    def handle(self, *args: object, **options: object) -> None:
        if options["reset"] or options["reset_only"]:
            if options["dry_run"]:
                self.stdout.write(
                    "Would delete existing network evolution runs, snapshots, and person metrics."
                )
                if options["reset_only"]:
                    return
            else:
                reset_stats = reset_network_evolution_tables()
                self.stdout.write(
                    self.style.SUCCESS(
                        "Deleted network evolution data: "
                        f"{reset_stats.runs_deleted} runs, "
                        f"{reset_stats.snapshots_deleted} snapshots, "
                        f"{reset_stats.person_metrics_deleted} person metric rows."
                    )
                )
                if options["reset_only"]:
                    return

        weeks = missing_evolution_weeks(
            start_week=options["start_week"],
            through_week=options["through_week"],
            bootstrap=bool(options["bootstrap"]),
            recompute=bool(options["recompute"]),
            max_weeks=options["max_weeks"],
        )
        if options["dry_run"]:
            if not weeks:
                self.stdout.write(
                    "No network evolution weeks would be calculated. "
                    "Pass --bootstrap for the initial historical backfill."
                )
                return
            self.stdout.write(
                f"Would calculate {len(weeks)} network evolution week(s): "
                f"{weeks[0]} through {weeks[-1]}."
            )
            return

        stats = calculate_network_evolution(
            start_week=options["start_week"],
            through_week=options["through_week"],
            bootstrap=bool(options["bootstrap"]),
            recompute=bool(options["recompute"]),
            max_weeks=options["max_weeks"],
            person_metric_limit=int(options["person_metric_limit"]),
            betweenness_sample_size=int(options["betweenness_sample_size"]),
            closeness_sample_size=int(options["closeness_sample_size"]),
        )
        if stats.run.status == stats.run.Status.SKIPPED:
            self.stdout.write(
                self.style.WARNING(
                    "Skipped network evolution calculation. "
                    "Pass --bootstrap for the initial historical backfill."
                )
            )
            return
        self.stdout.write(
            self.style.SUCCESS(
                f"Network evolution run {stats.run.id} {stats.run.status}: "
                f"{stats.weeks_calculated}/{stats.weeks_requested} week(s) calculated."
            )
        )


def parse_date(value: str) -> date:
    return date.fromisoformat(value)
