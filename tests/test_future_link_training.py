from datetime import datetime

from django.utils import timezone

from podcast_network.future_link_training import (
    FutureLinkCutConfig,
    FutureLinkSplitConfig,
    build_cut_plans,
    split_name,
)


def test_split_name_is_deterministic_for_pair_and_seed() -> None:
    cutoff_at = timezone.make_aware(datetime(2025, 1, 1, 0, 0))

    first = split_name(
        seed="example",
        cutoff_at=cutoff_at,
        podcast_id=123,
        canonical_id="person_abc",
        test_percent=20,
    )
    second = split_name(
        seed="example",
        cutoff_at=cutoff_at,
        podcast_id=123,
        canonical_id="person_abc",
        test_percent=20,
    )

    assert first == second
    assert first in {"train", "test"}


def test_build_cut_plans_uses_history_horizon_and_frequency() -> None:
    plans = build_cut_plans(
        first_episode_at=timezone.make_aware(datetime(2024, 1, 1, 12, 0)),
        latest_episode_at=timezone.make_aware(datetime(2024, 7, 1, 12, 0)),
        shard_base_uri="gs://bucket/future-links",
        split_config=FutureLinkSplitConfig(seed="seed", test_percent=25),
        cut_config=FutureLinkCutConfig(
            horizon_days=30,
            cut_frequency_days=30,
            min_history_days=60,
            max_cuts=3,
        ),
    )

    assert len(plans) == 3
    assert plans[0].cutoff_at.date().isoformat() == "2024-03-01"
    assert plans[0].horizon_start.date().isoformat() == "2024-03-01"
    assert plans[0].horizon_end.date().isoformat() == "2024-03-31"
    assert plans[0].split_seed == "seed"
    assert plans[0].test_percent == 25
    assert (
        plans[0].shard_uri
        == "gs://bucket/future-links/horizon_days=30/cutoff=2024-03-01/features.parquet"
    )


def test_build_cut_plans_returns_empty_when_horizon_would_be_unlabeled() -> None:
    plans = build_cut_plans(
        first_episode_at=timezone.make_aware(datetime(2024, 1, 1, 12, 0)),
        latest_episode_at=timezone.make_aware(datetime(2024, 2, 1, 12, 0)),
        shard_base_uri="gs://bucket/future-links",
        cut_config=FutureLinkCutConfig(horizon_days=90, min_history_days=365),
    )

    assert plans == []


def test_build_cut_plans_accepts_explicit_cutoff_bounds() -> None:
    plans = build_cut_plans(
        first_episode_at=timezone.make_aware(datetime(1970, 1, 1, 12, 0)),
        latest_episode_at=timezone.make_aware(datetime(2026, 5, 1, 12, 0)),
        shard_base_uri="gs://bucket/future-links",
        cut_config=FutureLinkCutConfig(
            horizon_days=90,
            cut_frequency_days=30,
            start_cutoff_at=timezone.make_aware(datetime(2025, 1, 1, 0, 0)),
            through_cutoff_at=timezone.make_aware(datetime(2025, 3, 1, 0, 0)),
        ),
    )

    assert [plan.cutoff_at.date().isoformat() for plan in plans] == [
        "2025-01-01",
        "2025-01-31",
    ]
