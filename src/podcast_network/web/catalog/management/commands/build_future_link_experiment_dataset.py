from __future__ import annotations

from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandParser
from django.utils import timezone

from podcast_network.future_link_features import build_balanced_experiment_dataset


class Command(BaseCommand):
    help = "Build a balanced one-cutoff feature table for future-link model experiments."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--output",
            default="data/reports/future_link_experiment_dataset.csv",
        )
        parser.add_argument("--cutoff", type=parse_datetime)
        parser.add_argument("--horizon-days", type=int, default=90)
        parser.add_argument("--max-degree", type=int, default=3)
        parser.add_argument("--negative-ratio", type=int, default=1)
        parser.add_argument("--sample-seed", default="future-link-experiment-v1")
        parser.add_argument("--split-seed", default="future-link-v1")
        parser.add_argument("--test-percent", type=int, default=20)
        parser.add_argument("--include-inactive-podcasts", action="store_true")
        parser.add_argument("--include-hosts", action="store_true")
        parser.add_argument("--min-podcast-guest-count", type=int, default=1)

    def handle(self, *args: object, **options: object) -> None:
        stats = build_balanced_experiment_dataset(
            output_path=Path(str(options["output"])),
            cutoff_at=options["cutoff"],
            horizon_days=int(options["horizon_days"]),
            max_degree=int(options["max_degree"]),
            negative_ratio=int(options["negative_ratio"]),
            sample_seed=str(options["sample_seed"]),
            split_seed=str(options["split_seed"]),
            test_percent=int(options["test_percent"]),
            active_podcasts_only=not bool(options["include_inactive_podcasts"]),
            exclude_hosts=not bool(options["include_hosts"]),
            min_podcast_guest_count=int(options["min_podcast_guest_count"]),
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Built future-link experiment dataset: "
                f"{stats.rows_written:,} rows, "
                f"{stats.positive_count:,} positives, "
                f"{stats.sampled_negative_count:,} sampled negatives. "
                f"Output: {stats.output_path}"
            )
        )
        self.stdout.write(f"Cutoff: {stats.cutoff_at.isoformat()}")
        self.stdout.write(f"Horizon end: {stats.horizon_end.isoformat()}")


def parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed

