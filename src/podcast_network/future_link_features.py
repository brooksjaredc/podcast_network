from __future__ import annotations

import csv
import hashlib
import heapq
import json
import math
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import networkx as nx
import numpy as np
from django.utils import timezone

from podcast_network.future_link_prediction import (
    HistoricalLinkData,
    LinkCandidate,
    build_historical_link_data,
    future_guest_links,
    latest_cutoff_for_labeling,
    podcasts_to_score,
)
from podcast_network.future_link_training import split_name
from podcast_network.web.catalog.models import Appearance, PersonEntityLink, Podcast

RECENT_WINDOWS = [30, 90, 180, 365]
LOGISTIC_FORWARD_FEATURES = [
    "shared_neighbor_score",
    "podcast_age_days",
    "guest_days_since_latest_appearance",
    "podcast_days_since_latest_guest",
    "podcast_repeat_guest_rate",
    "host_bridge_count",
    "host_bridge_weight",
    "podcast_degree_proxy",
    "guest_appearance_count_30d",
    "guest_appearance_count",
    "shared_guest_pair_count",
    "guest_appearance_count_365d",
]


@dataclass(frozen=True)
class ExperimentDatasetStats:
    cutoff_at: datetime
    horizon_end: datetime
    positive_count: int
    sampled_negative_count: int
    rows_written: int
    output_path: Path


@dataclass(frozen=True)
class FeatureMatrixStats:
    cutoff_at: datetime
    horizon_end: datetime
    row_count: int
    positive_count: int
    test_count: int
    output_dir: Path
    feature_names: list[str]


@dataclass(frozen=True)
class FeatureContext:
    cutoff_at: datetime
    historical: HistoricalLinkData
    podcast_guest_appearance_counts: Counter[int]
    guest_appearance_counts: Counter[str]
    podcast_recent_guest_counts: dict[int, Counter[int]]
    guest_recent_counts: dict[str, Counter[int]]
    podcast_first_seen_at: dict[int, datetime]
    podcast_latest_seen_at: dict[int, datetime]
    guest_first_seen_at: dict[str, datetime]
    guest_latest_seen_at: dict[str, datetime]
    podcast_categories: dict[int, set[str]]
    guest_categories: dict[str, set[str]]
    podcast_shared_neighbor_counts: dict[int, Counter[int]]
    podcast_host_bridge_counts: dict[int, Counter[int]]
    podcast_host_bridge_weights: dict[int, Counter[int]]


def build_balanced_experiment_dataset(
    *,
    output_path: Path,
    cutoff_at: datetime | None = None,
    horizon_days: int = 90,
    max_degree: int = 3,
    negative_ratio: int = 1,
    sample_seed: str = "future-link-experiment-v1",
    split_seed: str = "future-link-v1",
    test_percent: int = 20,
    active_podcasts_only: bool = True,
    exclude_hosts: bool = True,
    min_podcast_guest_count: int = 1,
) -> ExperimentDatasetStats:
    if cutoff_at is None:
        cutoff_at = latest_cutoff_for_labeling(horizon_days=horizon_days)
    if cutoff_at is None:
        raise ValueError("No cutoff could be inferred from linked episode dates.")
    if max_degree < 1:
        raise ValueError("max_degree must be at least 1")
    if negative_ratio < 1:
        raise ValueError("negative_ratio must be at least 1")

    horizon_end = cutoff_at + timedelta(days=horizon_days)
    historical = build_historical_link_data(cutoff_at=cutoff_at)
    future_links = future_guest_links(cutoff_at=cutoff_at, horizon_end=horizon_end)
    podcast_guest_counts = Counter(
        podcast_id for podcast_id, _canonical_id in historical.existing_guest_links
    )
    podcast_ids = podcasts_to_score(
        active_only=active_podcasts_only,
        available_podcast_ids=historical.podcast_ids,
        podcast_guest_counts=podcast_guest_counts,
        min_guest_count=min_podcast_guest_count,
    )

    positives = [
        candidate
        for candidate in iter_degree_limited_candidates(
            cutoff_at=cutoff_at,
            horizon_end=horizon_end,
            historical=historical,
            future_links=future_links,
            podcast_ids=podcast_ids,
            max_degree=max_degree,
            exclude_hosts=exclude_hosts,
        )
        if candidate.label
    ]
    negative_target = len(positives) * negative_ratio
    negatives = sample_negative_candidates(
        cutoff_at=cutoff_at,
        horizon_end=horizon_end,
        historical=historical,
        future_links=future_links,
        podcast_ids=podcast_ids,
        max_degree=max_degree,
        exclude_hosts=exclude_hosts,
        sample_size=negative_target,
        sample_seed=sample_seed,
    )

    context = build_feature_context(cutoff_at=cutoff_at, historical=historical)
    rows = []
    for candidate in positives + negatives:
        rows.append(
            feature_row(
                candidate=candidate,
                context=context,
                split_seed=split_seed,
                test_percent=test_percent,
            )
        )
    rows.sort(key=lambda row: (row["label"], row["podcast_id"], row["canonical_id"]))
    write_feature_rows(rows=rows, output_path=output_path)
    return ExperimentDatasetStats(
        cutoff_at=cutoff_at,
        horizon_end=horizon_end,
        positive_count=len(positives),
        sampled_negative_count=len(negatives),
        rows_written=len(rows),
        output_path=output_path,
    )


def build_full_feature_matrix(
    *,
    output_dir: Path,
    cutoff_at: datetime | None = None,
    horizon_days: int = 90,
    max_degree: int = 3,
    feature_names: list[str] | None = None,
    split_seed: str = "future-link-v1",
    test_percent: int = 20,
    active_podcasts_only: bool = True,
    exclude_hosts: bool = True,
    min_podcast_guest_count: int = 1,
    max_candidates: int | None = None,
) -> FeatureMatrixStats:
    if cutoff_at is None:
        cutoff_at = latest_cutoff_for_labeling(horizon_days=horizon_days)
    if cutoff_at is None:
        raise ValueError("No cutoff could be inferred from linked episode dates.")
    feature_names = feature_names or list(LOGISTIC_FORWARD_FEATURES)
    horizon_end = cutoff_at + timedelta(days=horizon_days)
    historical = build_historical_link_data(cutoff_at=cutoff_at)
    future_links = future_guest_links(cutoff_at=cutoff_at, horizon_end=horizon_end)
    podcast_guest_counts = Counter(
        podcast_id for podcast_id, _canonical_id in historical.existing_guest_links
    )
    podcast_ids = podcasts_to_score(
        active_only=active_podcasts_only,
        available_podcast_ids=historical.podcast_ids,
        podcast_guest_counts=podcast_guest_counts,
        min_guest_count=min_podcast_guest_count,
    )
    row_count = 0
    positive_count = 0
    for candidate in iter_degree_limited_candidates(
        cutoff_at=cutoff_at,
        horizon_end=horizon_end,
        historical=historical,
        future_links=future_links,
        podcast_ids=podcast_ids,
        max_degree=max_degree,
        exclude_hosts=exclude_hosts,
    ):
        row_count += 1
        positive_count += candidate.label
        if max_candidates is not None and row_count >= max_candidates:
            break

    output_dir.mkdir(parents=True, exist_ok=True)
    x_path = output_dir / "X.npy"
    y_path = output_dir / "y.npy"
    split_path = output_dir / "split.npy"
    x = np.lib.format.open_memmap(
        x_path,
        mode="w+",
        dtype=np.float32,
        shape=(row_count, len(feature_names)),
    )
    y = np.lib.format.open_memmap(y_path, mode="w+", dtype=np.uint8, shape=(row_count,))
    split = np.lib.format.open_memmap(split_path, mode="w+", dtype=np.uint8, shape=(row_count,))
    context = build_feature_context(cutoff_at=cutoff_at, historical=historical)
    test_count = 0
    candidates = iter_degree_limited_candidates(
        cutoff_at=cutoff_at,
        horizon_end=horizon_end,
        historical=historical,
        future_links=future_links,
        podcast_ids=podcast_ids,
        max_degree=max_degree,
        exclude_hosts=exclude_hosts,
    )
    for index, candidate in enumerate(candidates):
        if max_candidates is not None and index >= max_candidates:
            break
        x[index, :] = selected_feature_values(
            candidate=candidate,
            context=context,
            feature_names=feature_names,
        )
        y[index] = candidate.label
        split_value = int(
            split_name(
                seed=split_seed,
                cutoff_at=cutoff_at,
                podcast_id=candidate.podcast_id,
                canonical_id=candidate.canonical_id,
                test_percent=test_percent,
            )
            == "test"
        )
        split[index] = split_value
        test_count += split_value
    x.flush()
    y.flush()
    split.flush()
    metadata = {
        "cutoff_at": cutoff_at.isoformat(),
        "horizon_end": horizon_end.isoformat(),
        "horizon_days": horizon_days,
        "max_degree": max_degree,
        "row_count": row_count,
        "positive_count": positive_count,
        "test_count": test_count,
        "split_seed": split_seed,
        "test_percent": test_percent,
        "feature_names": feature_names,
        "x_path": str(x_path),
        "y_path": str(y_path),
        "split_path": str(split_path),
    }
    (output_dir / "metadata.json").write_text(
        json_dumps(metadata),
        encoding="utf-8",
    )
    return FeatureMatrixStats(
        cutoff_at=cutoff_at,
        horizon_end=horizon_end,
        row_count=row_count,
        positive_count=positive_count,
        test_count=test_count,
        output_dir=output_dir,
        feature_names=feature_names,
    )


def iter_degree_limited_candidates(
    *,
    cutoff_at: datetime,
    horizon_end: datetime,
    historical: HistoricalLinkData,
    future_links: set[tuple[int, str]],
    podcast_ids: set[int],
    max_degree: int,
    exclude_hosts: bool,
) -> Iterator[LinkCandidate]:
    for podcast_id in sorted(podcast_ids):
        source = ("podcast", podcast_id)
        if source not in historical.graph:
            continue
        distances = nx.single_source_shortest_path_length(
            historical.graph,
            source,
            cutoff=max_degree,
        )
        for node, distance in distances.items():
            if node[0] != "person":
                continue
            canonical_id = node[1]
            pair = (podcast_id, canonical_id)
            if pair in historical.existing_guest_links:
                continue
            if canonical_id not in historical.guest_canonical_ids:
                continue
            if exclude_hosts and pair in historical.host_links:
                continue
            yield LinkCandidate(
                cutoff_at=cutoff_at,
                horizon_end=horizon_end,
                podcast_id=podcast_id,
                canonical_id=canonical_id,
                distance=distance,
                label=int(pair in future_links),
            )


def sample_negative_candidates(
    *,
    cutoff_at: datetime,
    horizon_end: datetime,
    historical: HistoricalLinkData,
    future_links: set[tuple[int, str]],
    podcast_ids: set[int],
    max_degree: int,
    exclude_hosts: bool,
    sample_size: int,
    sample_seed: str,
) -> list[LinkCandidate]:
    if sample_size <= 0:
        return []
    heap: list[tuple[int, int, LinkCandidate]] = []
    sequence = 0
    for candidate in iter_degree_limited_candidates(
        cutoff_at=cutoff_at,
        horizon_end=horizon_end,
        historical=historical,
        future_links=future_links,
        podcast_ids=podcast_ids,
        max_degree=max_degree,
        exclude_hosts=exclude_hosts,
    ):
        if candidate.label:
            continue
        score = deterministic_sample_score(
            sample_seed=sample_seed,
            cutoff_at=cutoff_at,
            podcast_id=candidate.podcast_id,
            canonical_id=candidate.canonical_id,
        )
        item = (-score, sequence, candidate)
        sequence += 1
        if len(heap) < sample_size:
            heapq.heappush(heap, item)
        elif item > heap[0]:
            heapq.heapreplace(heap, item)
    return [item[2] for item in sorted(heap, reverse=True)]


def deterministic_sample_score(
    *,
    sample_seed: str,
    cutoff_at: datetime,
    podcast_id: int,
    canonical_id: str,
) -> int:
    key = f"{sample_seed}|{cutoff_at.isoformat()}|{podcast_id}|{canonical_id}"
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:16], 16)


def build_feature_context(
    *,
    cutoff_at: datetime,
    historical: HistoricalLinkData,
    link_created_before: datetime | None = None,
) -> FeatureContext:
    podcast_guest_appearance_counts: Counter[int] = Counter()
    guest_appearance_counts: Counter[str] = Counter()
    podcast_recent_guest_counts: dict[int, Counter[int]] = {}
    guest_recent_counts: dict[str, Counter[int]] = {}
    podcast_first_seen_at: dict[int, datetime] = {}
    podcast_latest_seen_at: dict[int, datetime] = {}
    guest_first_seen_at: dict[str, datetime] = {}
    guest_latest_seen_at: dict[str, datetime] = {}
    guest_categories: dict[str, set[str]] = {}
    podcast_categories = load_podcast_categories()

    links = PersonEntityLink.objects.filter(
        observation__role=Appearance.Role.GUEST,
        observation__episode__published_at__lt=cutoff_at,
    )
    if link_created_before is not None:
        links = links.filter(created_at__lt=link_created_before)
    rows = (
        links.exclude(observation__episode__published_at__isnull=True)
        .values_list(
            "observation__podcast_id",
            "canonical_id",
            "observation__episode__published_at",
        )
    )
    for podcast_id, canonical_id, published_at in rows.iterator(chunk_size=20_000):
        podcast_guest_appearance_counts[podcast_id] += 1
        guest_appearance_counts[canonical_id] += 1
        update_bounds(podcast_first_seen_at, podcast_latest_seen_at, podcast_id, published_at)
        update_bounds(guest_first_seen_at, guest_latest_seen_at, canonical_id, published_at)
        for window in RECENT_WINDOWS:
            if published_at >= cutoff_at - timedelta(days=window):
                podcast_recent_guest_counts.setdefault(podcast_id, Counter())[window] += 1
                guest_recent_counts.setdefault(canonical_id, Counter())[window] += 1
        guest_categories.setdefault(canonical_id, set()).update(
            podcast_categories.get(podcast_id, set())
        )

    return FeatureContext(
        cutoff_at=cutoff_at,
        historical=historical,
        podcast_guest_appearance_counts=podcast_guest_appearance_counts,
        guest_appearance_counts=guest_appearance_counts,
        podcast_recent_guest_counts=podcast_recent_guest_counts,
        guest_recent_counts=guest_recent_counts,
        podcast_first_seen_at=podcast_first_seen_at,
        podcast_latest_seen_at=podcast_latest_seen_at,
        guest_first_seen_at=guest_first_seen_at,
        guest_latest_seen_at=guest_latest_seen_at,
        podcast_categories=podcast_categories,
        guest_categories=guest_categories,
        podcast_shared_neighbor_counts=podcast_shared_neighbor_counts(historical),
        podcast_host_bridge_counts=podcast_host_bridge_counts(historical),
        podcast_host_bridge_weights=podcast_host_bridge_weights(historical),
    )


def podcast_shared_neighbor_counts(
    historical: HistoricalLinkData,
) -> dict[int, Counter[int]]:
    counts: dict[int, Counter[int]] = {}
    for podcast_id, target_guests in historical.podcast_guest_ids.items():
        podcast_counts: Counter[int] = Counter()
        for target_guest_id in target_guests:
            for neighbor_podcast_id in historical.guest_podcast_ids.get(target_guest_id, set()):
                if neighbor_podcast_id != podcast_id:
                    podcast_counts[neighbor_podcast_id] += 1
        counts[podcast_id] = podcast_counts
    return counts


def podcast_host_bridge_counts(
    historical: HistoricalLinkData,
) -> dict[int, Counter[int]]:
    counts: dict[int, Counter[int]] = {}
    for podcast_id, host_ids in historical.podcast_host_ids.items():
        podcast_counts: Counter[int] = Counter()
        for host_id in host_ids:
            for bridge_podcast_id in historical.person_podcast_ids.get(host_id, set()):
                podcast_counts[bridge_podcast_id] += 1
        counts[podcast_id] = podcast_counts
    return counts


def podcast_host_bridge_weights(
    historical: HistoricalLinkData,
) -> dict[int, Counter[int]]:
    weights: dict[int, Counter[int]] = {}
    for podcast_id, host_ids in historical.podcast_host_ids.items():
        podcast_weights: Counter[int] = Counter()
        for host_id in host_ids:
            for bridge_podcast_id in historical.person_podcast_ids.get(host_id, set()):
                podcast_weights[bridge_podcast_id] += 1 + len(
                    historical.podcast_guest_ids.get(bridge_podcast_id, set())
                )
        weights[podcast_id] = podcast_weights
    return weights


def update_bounds(
    first_seen: dict[int | str, datetime],
    latest_seen: dict[int | str, datetime],
    key: int | str,
    value: datetime,
) -> None:
    if key not in first_seen or value < first_seen[key]:
        first_seen[key] = value
    if key not in latest_seen or value > latest_seen[key]:
        latest_seen[key] = value


def feature_row(
    *,
    candidate: LinkCandidate,
    context: FeatureContext,
    split_seed: str,
    test_percent: int,
) -> dict[str, int | float | str]:
    historical = context.historical
    podcast_id = candidate.podcast_id
    canonical_id = candidate.canonical_id
    target_guests = historical.podcast_guest_ids.get(podcast_id, set())
    candidate_podcasts = historical.guest_podcast_ids.get(canonical_id, set())
    neighbor_podcast_counts: Counter[int] = Counter()
    shared_guest_pair_count = 0
    for target_guest_id in target_guests:
        shared_podcasts = candidate_podcasts & historical.guest_podcast_ids.get(
            target_guest_id,
            set(),
        )
        shared_guest_pair_count += len(shared_podcasts)
        for neighbor_podcast_id in shared_podcasts:
            if neighbor_podcast_id != podcast_id:
                neighbor_podcast_counts[neighbor_podcast_id] += 1

    host_bridge_count = 0
    host_bridge_weight = 0
    for host_id in historical.podcast_host_ids.get(podcast_id, set()):
        shared_host_podcasts = candidate_podcasts & historical.person_podcast_ids.get(
            host_id,
            set(),
        )
        host_bridge_count += len(shared_host_podcasts)
        host_bridge_weight += sum(
            1 + len(historical.podcast_guest_ids.get(shared_podcast_id, set()))
            for shared_podcast_id in shared_host_podcasts
        )

    podcast_categories = context.podcast_categories.get(podcast_id, set())
    guest_categories = context.guest_categories.get(canonical_id, set())
    category_intersection = podcast_categories & guest_categories
    category_union = podcast_categories | guest_categories
    podcast_age_days = days_since(context.podcast_first_seen_at.get(podcast_id), context.cutoff_at)
    guest_age_days = days_since(context.guest_first_seen_at.get(canonical_id), context.cutoff_at)

    row: dict[str, int | float | str] = {
        "cutoff_at": context.cutoff_at.isoformat(),
        "podcast_id": podcast_id,
        "canonical_id": canonical_id,
        "label": candidate.label,
        "split": split_name(
            seed=split_seed,
            cutoff_at=context.cutoff_at,
            podcast_id=podcast_id,
            canonical_id=canonical_id,
            test_percent=test_percent,
        ),
        "distance": candidate.distance,
        "podcast_guest_appearance_count": context.podcast_guest_appearance_counts[podcast_id],
        "podcast_unique_guest_count": len(target_guests),
        "podcast_repeat_guest_rate": safe_ratio(
            context.podcast_guest_appearance_counts[podcast_id] - len(target_guests),
            context.podcast_guest_appearance_counts[podcast_id],
        ),
        "podcast_age_days": podcast_age_days,
        "podcast_days_since_latest_guest": days_since(
            context.podcast_latest_seen_at.get(podcast_id),
            context.cutoff_at,
        ),
        "guest_appearance_count": context.guest_appearance_counts[canonical_id],
        "guest_unique_podcast_count": len(candidate_podcasts),
        "guest_repeat_appearance_rate": safe_ratio(
            context.guest_appearance_counts[canonical_id] - len(candidate_podcasts),
            context.guest_appearance_counts[canonical_id],
        ),
        "guest_age_days": guest_age_days,
        "guest_days_since_latest_appearance": days_since(
            context.guest_latest_seen_at.get(canonical_id),
            context.cutoff_at,
        ),
        "shared_guest_pair_count": shared_guest_pair_count,
        "shared_neighbor_podcast_count": len(neighbor_podcast_counts),
        "shared_neighbor_score": sum(neighbor_podcast_counts.values()),
        "max_shared_guests_on_neighbor_podcast": max(neighbor_podcast_counts.values(), default=0),
        "jaccard_candidate_podcasts_target_guests": safe_ratio(
            len(neighbor_podcast_counts),
            len(candidate_podcasts | target_guest_podcasts(target_guests, historical)),
        ),
        "host_bridge_count": host_bridge_count,
        "host_bridge_weight": host_bridge_weight,
        "podcast_category_count": len(podcast_categories),
        "guest_category_count": len(guest_categories),
        "category_overlap_count": len(category_intersection),
        "category_jaccard": safe_ratio(len(category_intersection), len(category_union)),
        "podcast_degree_proxy": len(historical.graph[("podcast", podcast_id)])
        if ("podcast", podcast_id) in historical.graph
        else 0,
        "guest_degree_proxy": len(historical.graph[("person", canonical_id)])
        if ("person", canonical_id) in historical.graph
        else 0,
        "guest_podcast_count_ratio": safe_ratio(
            len(candidate_podcasts),
            len(historical.podcast_ids),
        ),
        "guest_momentum_90_365": safe_ratio(
            context.guest_recent_counts.get(canonical_id, Counter())[90] * 4,
            context.guest_recent_counts.get(canonical_id, Counter())[365],
        ),
        "podcast_momentum_90_365": safe_ratio(
            context.podcast_recent_guest_counts.get(podcast_id, Counter())[90] * 4,
            context.podcast_recent_guest_counts.get(podcast_id, Counter())[365],
        ),
    }
    for window in RECENT_WINDOWS:
        row[f"podcast_guest_count_{window}d"] = context.podcast_recent_guest_counts.get(
            podcast_id, Counter()
        )[window]
        row[f"guest_appearance_count_{window}d"] = context.guest_recent_counts.get(
            canonical_id, Counter()
        )[window]
    return row


def selected_feature_values(
    *,
    candidate: LinkCandidate,
    context: FeatureContext,
    feature_names: list[str],
) -> list[float]:
    features = selected_feature_map(candidate=candidate, context=context)
    return [float(features.get(feature_name, 0.0)) for feature_name in feature_names]


def selected_feature_map(
    *,
    candidate: LinkCandidate,
    context: FeatureContext,
) -> dict[str, float]:
    historical = context.historical
    podcast_id = candidate.podcast_id
    canonical_id = candidate.canonical_id
    target_guests = historical.podcast_guest_ids.get(podcast_id, set())
    candidate_podcasts = historical.guest_podcast_ids.get(canonical_id, set())
    shared_neighbor_counts = context.podcast_shared_neighbor_counts.get(podcast_id, Counter())
    host_bridge_counts = context.podcast_host_bridge_counts.get(podcast_id, Counter())
    host_bridge_weights = context.podcast_host_bridge_weights.get(podcast_id, Counter())
    shared_neighbor_score = sum(
        shared_neighbor_counts[neighbor_podcast_id] for neighbor_podcast_id in candidate_podcasts
    )
    shared_guest_pair_count = shared_neighbor_score
    host_bridge_count = sum(
        host_bridge_counts[bridge_podcast_id] for bridge_podcast_id in candidate_podcasts
    )
    host_bridge_weight = sum(
        host_bridge_weights[bridge_podcast_id] for bridge_podcast_id in candidate_podcasts
    )

    podcast_guest_appearance_count = context.podcast_guest_appearance_counts[podcast_id]
    target_guest_count = len(target_guests)
    return {
        "shared_neighbor_score": float(shared_neighbor_score),
        "podcast_age_days": days_since(
            context.podcast_first_seen_at.get(podcast_id),
            context.cutoff_at,
        ),
        "guest_days_since_latest_appearance": days_since(
            context.guest_latest_seen_at.get(canonical_id),
            context.cutoff_at,
        ),
        "podcast_days_since_latest_guest": days_since(
            context.podcast_latest_seen_at.get(podcast_id),
            context.cutoff_at,
        ),
        "podcast_repeat_guest_rate": safe_ratio(
            podcast_guest_appearance_count - target_guest_count,
            podcast_guest_appearance_count,
        ),
        "host_bridge_count": float(host_bridge_count),
        "host_bridge_weight": float(host_bridge_weight),
        "podcast_degree_proxy": float(
            len(historical.graph[("podcast", podcast_id)])
            if ("podcast", podcast_id) in historical.graph
            else 0
        ),
        "guest_appearance_count_30d": float(
            context.guest_recent_counts.get(canonical_id, Counter())[30]
        ),
        "guest_appearance_count": float(context.guest_appearance_counts[canonical_id]),
        "shared_guest_pair_count": float(shared_guest_pair_count),
        "guest_appearance_count_365d": float(
            context.guest_recent_counts.get(canonical_id, Counter())[365]
        ),
    }


def target_guest_podcasts(target_guests: set[str], historical: HistoricalLinkData) -> set[int]:
    podcast_ids: set[int] = set()
    for target_guest_id in target_guests:
        podcast_ids.update(historical.guest_podcast_ids.get(target_guest_id, set()))
    return podcast_ids


def load_podcast_categories() -> dict[int, set[str]]:
    categories: dict[int, set[str]] = {}
    for podcast_id, metadata in Podcast.objects.values_list("id", "metadata"):
        values: set[str] = set()
        if isinstance(metadata, dict):
            for key in ["categories", "genres", "chart_categories"]:
                raw_value = metadata.get(key)
                if isinstance(raw_value, list):
                    values.update(
                        str(item).strip().lower() for item in raw_value if str(item).strip()
                    )
                elif isinstance(raw_value, str) and raw_value.strip():
                    values.add(raw_value.strip().lower())
        categories[podcast_id] = values
    return categories


def safe_ratio(numerator: float, denominator: float) -> float:
    if not denominator:
        return 0.0
    value = numerator / denominator
    if math.isnan(value) or math.isinf(value):
        return 0.0
    return float(value)


def days_since(value: datetime | None, cutoff_at: datetime) -> float:
    if value is None:
        return 0.0
    if timezone.is_naive(value) and timezone.is_aware(cutoff_at):
        value = timezone.make_aware(value, timezone.get_current_timezone())
    return max(0.0, (cutoff_at - value).total_seconds() / 86400.0)


def write_feature_rows(*, rows: list[dict[str, int | float | str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        output_path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def json_dumps(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"
