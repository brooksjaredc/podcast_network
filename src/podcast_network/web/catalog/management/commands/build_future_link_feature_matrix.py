from __future__ import annotations

from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandParser
from django.utils import timezone

from podcast_network.future_link_features import build_full_feature_matrix


class Command(BaseCommand):
    help = "Materialize the full one-cutoff 12-feature future-link matrix as NumPy arrays."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--output-dir", default="data/reports/future_link_full_matrix")
        parser.add_argument("--cutoff", type=parse_datetime)
        parser.add_argument("--horizon-days", type=int, default=90)
        parser.add_argument("--max-degree", type=int, default=3)
        parser.add_argument("--split-seed", default="future-link-v1")
        parser.add_argument("--test-percent", type=int, default=20)
        parser.add_argument("--include-inactive-podcasts", action="store_true")
        parser.add_argument("--include-hosts", action="store_true")
        parser.add_argument("--min-podcast-guest-count", type=int, default=1)
        parser.add_argument(
            "--max-candidates",
            type=int,
            help="Limit rows for smoke tests. Omit for the full candidate universe.",
        )

    def handle(self, *args: object, **options: object) -> None:
        stats = build_full_feature_matrix(
            output_dir=Path(str(options["output_dir"])),
            cutoff_at=options["cutoff"],
            horizon_days=int(options["horizon_days"]),
            max_degree=int(options["max_degree"]),
            split_seed=str(options["split_seed"]),
            test_percent=int(options["test_percent"]),
            active_podcasts_only=not bool(options["include_inactive_podcasts"]),
            exclude_hosts=not bool(options["include_hosts"]),
            min_podcast_guest_count=int(options["min_podcast_guest_count"]),
            max_candidates=options["max_candidates"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Built future-link feature matrix: "
                f"{stats.row_count:,} rows, "
                f"{stats.positive_count:,} positives, "
                f"{stats.test_count:,} test rows. "
                f"Output: {stats.output_dir}"
            )
        )
        self.stdout.write(f"Cutoff: {stats.cutoff_at.isoformat()}")
        self.stdout.write(f"Horizon end: {stats.horizon_end.isoformat()}")
        self.stdout.write("Features:")
        for feature_name in stats.feature_names:
            self.stdout.write(f"  {feature_name}")


def parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed

