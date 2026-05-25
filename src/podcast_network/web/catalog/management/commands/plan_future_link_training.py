from __future__ import annotations

from datetime import date, datetime, time

from django.core.management.base import BaseCommand, CommandParser
from django.utils import timezone

from podcast_network.future_links.training import (
    FutureLinkCutConfig,
    FutureLinkSplitConfig,
    database_cut_plans,
    episode_date_bounds,
)


class Command(BaseCommand):
    help = "Preview rolling date cuts, deterministic splits, and feature shard paths."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--horizon-days", type=int, default=90)
        parser.add_argument("--cut-frequency-days", type=int, default=30)
        parser.add_argument("--min-history-days", type=int, default=365)
        parser.add_argument("--label-gap-days", type=int, default=0)
        parser.add_argument("--start-cutoff", type=parse_date)
        parser.add_argument("--through-cutoff", type=parse_date)
        parser.add_argument("--max-cuts", type=int)
        parser.add_argument("--split-seed", default="future-link-v1")
        parser.add_argument("--test-percent", type=int, default=20)
        parser.add_argument(
            "--shard-base-uri",
            default="gs://podcast-network-ml/future-link-prediction",
            help="Base URI for temporary per-cut feature shards.",
        )

    def handle(self, *args: object, **options: object) -> None:
        bounds = episode_date_bounds()
        if bounds is None:
            self.stdout.write(self.style.WARNING("No dated episodes found."))
            return

        split_config = FutureLinkSplitConfig(
            seed=str(options["split_seed"]),
            test_percent=int(options["test_percent"]),
        )
        cut_config = FutureLinkCutConfig(
            horizon_days=int(options["horizon_days"]),
            cut_frequency_days=int(options["cut_frequency_days"]),
            min_history_days=int(options["min_history_days"]),
            label_gap_days=int(options["label_gap_days"]),
            start_cutoff_at=start_of_local_day(options["start_cutoff"]),
            through_cutoff_at=start_of_local_day(options["through_cutoff"]),
            max_cuts=options["max_cuts"],
        )
        plans = database_cut_plans(
            shard_base_uri=str(options["shard_base_uri"]),
            split_config=split_config,
            cut_config=cut_config,
        )
        first_episode_at, latest_episode_at = bounds
        self.stdout.write(f"Episode date bounds: {first_episode_at} through {latest_episode_at}")
        self.stdout.write(f"Planned date cuts: {len(plans):,}")
        self.stdout.write(f"Split seed: {split_config.seed}")
        self.stdout.write(f"Test percent: {split_config.test_percent}")
        if not plans:
            return
        self.stdout.write(f"First cutoff: {plans[0].cutoff_at}")
        self.stdout.write(f"Last cutoff: {plans[-1].cutoff_at}")
        self.stdout.write("Cut shards:")
        for plan in plans[:10]:
            self.stdout.write(
                f"  {plan.cutoff_at.date().isoformat()} "
                f"labels={plan.horizon_start.date().isoformat()}.."
                f"{plan.horizon_end.date().isoformat()} "
                f"shard={plan.shard_uri}"
            )
        if len(plans) > 10:
            self.stdout.write(f"  ... {len(plans) - 10:,} more")


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def start_of_local_day(value: date | None) -> datetime | None:
    if value is None:
        return None
    return timezone.make_aware(
        datetime.combine(value, time.min),
        timezone.get_current_timezone(),
    )
