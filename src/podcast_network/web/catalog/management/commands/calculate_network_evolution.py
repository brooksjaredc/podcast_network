from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand, CommandParser

from podcast_network.network_evolution import (
    calculate_network_evolution,
    missing_evolution_weeks,
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
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args: object, **options: object) -> None:
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
