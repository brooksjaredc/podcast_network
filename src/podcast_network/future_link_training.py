from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from django.utils import timezone

from podcast_network.web.catalog.models import Episode


@dataclass(frozen=True)
class FutureLinkSplitConfig:
    seed: str = "future-link-v1"
    test_percent: int = 20

    def __post_init__(self) -> None:
        if not 0 < self.test_percent < 100:
            raise ValueError("test_percent must be between 1 and 99")


@dataclass(frozen=True)
class FutureLinkCutConfig:
    horizon_days: int = 90
    cut_frequency_days: int = 30
    min_history_days: int = 365
    label_gap_days: int = 0
    start_cutoff_at: datetime | None = None
    through_cutoff_at: datetime | None = None
    max_cuts: int | None = None

    def __post_init__(self) -> None:
        if self.horizon_days < 1:
            raise ValueError("horizon_days must be at least 1")
        if self.cut_frequency_days < 1:
            raise ValueError("cut_frequency_days must be at least 1")
        if self.min_history_days < 0:
            raise ValueError("min_history_days must be non-negative")
        if self.label_gap_days < 0:
            raise ValueError("label_gap_days must be non-negative")


@dataclass(frozen=True)
class FutureLinkCutPlan:
    cutoff_at: datetime
    horizon_start: datetime
    horizon_end: datetime
    split_seed: str
    test_percent: int
    shard_uri: str


def split_bucket(
    *,
    seed: str,
    cutoff_at: datetime,
    podcast_id: int,
    canonical_id: str,
) -> int:
    key = "|".join(
        [
            seed,
            cutoff_at.isoformat(),
            str(podcast_id),
            canonical_id,
        ]
    )
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 100


def split_name(
    *,
    seed: str,
    cutoff_at: datetime,
    podcast_id: int,
    canonical_id: str,
    test_percent: int = 20,
) -> str:
    config = FutureLinkSplitConfig(seed=seed, test_percent=test_percent)
    bucket = split_bucket(
        seed=config.seed,
        cutoff_at=cutoff_at,
        podcast_id=podcast_id,
        canonical_id=canonical_id,
    )
    return "test" if bucket >= 100 - config.test_percent else "train"


def build_cut_plans(
    *,
    first_episode_at: datetime,
    latest_episode_at: datetime,
    shard_base_uri: str,
    split_config: FutureLinkSplitConfig | None = None,
    cut_config: FutureLinkCutConfig | None = None,
) -> list[FutureLinkCutPlan]:
    split_config = split_config or FutureLinkSplitConfig()
    cut_config = cut_config or FutureLinkCutConfig()
    first_cutoff = cut_config.start_cutoff_at or start_of_day(
        first_episode_at + timedelta(days=cut_config.min_history_days)
    )
    latest_cutoff = cut_config.through_cutoff_at or start_of_day(
        latest_episode_at
        - timedelta(days=cut_config.horizon_days)
        - timedelta(days=cut_config.label_gap_days)
    )
    if first_cutoff > latest_cutoff:
        return []

    plans = []
    cutoff_at = first_cutoff
    while cutoff_at <= latest_cutoff:
        horizon_start = cutoff_at + timedelta(days=cut_config.label_gap_days)
        horizon_end = horizon_start + timedelta(days=cut_config.horizon_days)
        plans.append(
            FutureLinkCutPlan(
                cutoff_at=cutoff_at,
                horizon_start=horizon_start,
                horizon_end=horizon_end,
                split_seed=split_config.seed,
                test_percent=split_config.test_percent,
                shard_uri=cut_shard_uri(
                    base_uri=shard_base_uri,
                    cutoff_at=cutoff_at,
                    horizon_days=cut_config.horizon_days,
                ),
            )
        )
        if cut_config.max_cuts is not None and len(plans) >= cut_config.max_cuts:
            break
        cutoff_at += timedelta(days=cut_config.cut_frequency_days)
    return plans


def database_cut_plans(
    *,
    shard_base_uri: str,
    split_config: FutureLinkSplitConfig | None = None,
    cut_config: FutureLinkCutConfig | None = None,
) -> list[FutureLinkCutPlan]:
    split_config = split_config or FutureLinkSplitConfig()
    cut_config = cut_config or FutureLinkCutConfig()
    bounds = episode_date_bounds()
    if bounds is None:
        return []
    first_episode_at, latest_episode_at = bounds
    return build_cut_plans(
        first_episode_at=first_episode_at,
        latest_episode_at=latest_episode_at,
        shard_base_uri=shard_base_uri,
        split_config=split_config,
        cut_config=cut_config,
    )


def episode_date_bounds() -> tuple[datetime, datetime] | None:
    first_episode_at = (
        Episode.objects.exclude(published_at__isnull=True)
        .order_by("published_at")
        .values_list("published_at", flat=True)
        .first()
    )
    latest_episode_at = (
        Episode.objects.exclude(published_at__isnull=True)
        .order_by("-published_at")
        .values_list("published_at", flat=True)
        .first()
    )
    if first_episode_at is None or latest_episode_at is None:
        return None
    return first_episode_at, latest_episode_at


def start_of_day(value: datetime) -> datetime:
    local_value = timezone.localtime(value) if timezone.is_aware(value) else value
    local_start = datetime.combine(local_value.date(), time.min)
    return timezone.make_aware(local_start, timezone.get_current_timezone())


def cut_shard_uri(*, base_uri: str, cutoff_at: datetime, horizon_days: int) -> str:
    return (
        base_uri.rstrip("/")
        + f"/horizon_days={horizon_days}/cutoff={cutoff_at.date().isoformat()}/features.parquet"
    )
