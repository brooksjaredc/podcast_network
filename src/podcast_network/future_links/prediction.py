from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import networkx as nx

from podcast_network.web.catalog.models import Appearance, PersonEntityLink, Podcast

PodcastNode = tuple[str, int]
PersonNode = tuple[str, str]
GraphNode = PodcastNode | PersonNode


@dataclass(frozen=True)
class LinkCandidate:
    cutoff_at: datetime
    horizon_end: datetime
    podcast_id: int
    canonical_id: str
    distance: int
    label: int
    retrieval_score: float = 0.0


@dataclass(frozen=True)
class LinkCandidateStats:
    cutoff_at: datetime
    horizon_end: datetime
    max_degree: int
    podcast_count: int
    person_count: int
    train_edge_count: int
    future_positive_count: int
    candidate_count: int
    positive_count: int
    negative_count: int
    positives_missed_by_retrieval: int
    positives_excluded_existing_link: int
    positives_excluded_host: int
    distance_counts: dict[int, int] = field(default_factory=dict)
    distance_positive_counts: dict[int, int] = field(default_factory=dict)

    @property
    def positive_rate(self) -> float:
        if self.candidate_count == 0:
            return 0.0
        return self.positive_count / self.candidate_count

    @property
    def retrieval_recall(self) -> float:
        eligible_positives = (
            self.future_positive_count
            - self.positives_excluded_existing_link
            - self.positives_excluded_host
        )
        if eligible_positives <= 0:
            return 0.0
        return self.positive_count / eligible_positives


@dataclass(frozen=True)
class LinkCandidateResult:
    candidates: list[LinkCandidate]
    stats: LinkCandidateStats


@dataclass(frozen=True)
class PodcastEligibilityStats:
    total_podcasts: int
    active_podcasts: int
    historical_linked_podcasts: int
    active_historical_linked_podcasts: int
    scored_podcasts: int
    inactive_historical_linked_podcasts: int
    active_without_historical_links: int


@dataclass(frozen=True)
class CandidateSetComparison:
    baseline_candidate_count: int
    heuristic_candidate_count: int
    baseline_positive_count: int
    heuristic_positive_count: int
    positives_lost_from_baseline: int
    positives_added_outside_baseline: int

    @property
    def row_reduction(self) -> float:
        if self.baseline_candidate_count == 0:
            return 0.0
        return 1 - (self.heuristic_candidate_count / self.baseline_candidate_count)

    @property
    def positive_retention(self) -> float:
        if self.baseline_positive_count == 0:
            return 0.0
        return (
            self.heuristic_positive_count - self.positives_added_outside_baseline
        ) / self.baseline_positive_count


@dataclass(frozen=True)
class HistoricalLinkData:
    graph: nx.Graph
    existing_guest_links: set[tuple[int, str]]
    host_links: set[tuple[int, str]]
    podcast_ids: set[int]
    guest_canonical_ids: set[str]
    podcast_guest_ids: dict[int, set[str]]
    guest_podcast_ids: dict[str, set[int]]
    podcast_host_ids: dict[int, set[str]]
    person_podcast_ids: dict[str, set[int]]


def build_degree_limited_link_candidates(
    *,
    cutoff_at: datetime,
    horizon_days: int = 90,
    max_degree: int = 3,
    active_podcasts_only: bool = True,
    exclude_hosts: bool = True,
    min_podcast_guest_count: int = 1,
) -> LinkCandidateResult:
    """Build one cutoff of podcast/person candidates with future-link labels."""
    if max_degree < 1:
        raise ValueError("max_degree must be at least 1")
    if horizon_days < 1:
        raise ValueError("horizon_days must be at least 1")

    horizon_end = cutoff_at + timedelta(days=horizon_days)
    historical = build_historical_link_data(cutoff_at=cutoff_at)
    future_positive_links = future_guest_links(cutoff_at=cutoff_at, horizon_end=horizon_end)
    podcast_guest_counts = Counter(
        podcast_id for podcast_id, _canonical_id in historical.existing_guest_links
    )
    podcast_ids = podcasts_to_score(
        active_only=active_podcasts_only,
        available_podcast_ids=historical.podcast_ids,
        podcast_guest_counts=podcast_guest_counts,
        min_guest_count=min_podcast_guest_count,
    )

    candidates: list[LinkCandidate] = []
    distance_counts: Counter[int] = Counter()
    distance_positive_counts: Counter[int] = Counter()
    seen_pairs: set[tuple[int, str]] = set()
    for podcast_id in sorted(podcast_ids):
        source: PodcastNode = ("podcast", podcast_id)
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
            if pair in seen_pairs or pair in historical.existing_guest_links:
                continue
            if canonical_id not in historical.guest_canonical_ids:
                continue
            if exclude_hosts and pair in historical.host_links:
                continue
            seen_pairs.add(pair)
            label = int(pair in future_positive_links)
            candidates.append(
                LinkCandidate(
                    cutoff_at=cutoff_at,
                    horizon_end=horizon_end,
                    podcast_id=podcast_id,
                    canonical_id=canonical_id,
                    distance=distance,
                    label=label,
                )
            )
            distance_counts[distance] += 1
            if label:
                distance_positive_counts[distance] += 1

    candidate_pairs = {(candidate.podcast_id, candidate.canonical_id) for candidate in candidates}
    existing_positive_links = future_positive_links & historical.existing_guest_links
    host_positive_links = future_positive_links & historical.host_links if exclude_hosts else set()
    positive_count = sum(candidate.label for candidate in candidates)
    positives_missed = len(
        future_positive_links
        - candidate_pairs
        - existing_positive_links
        - host_positive_links
    )
    stats = LinkCandidateStats(
        cutoff_at=cutoff_at,
        horizon_end=horizon_end,
        max_degree=max_degree,
        podcast_count=len(podcast_ids),
        person_count=len(historical.guest_canonical_ids),
        train_edge_count=len(historical.existing_guest_links),
        future_positive_count=len(future_positive_links),
        candidate_count=len(candidates),
        positive_count=positive_count,
        negative_count=len(candidates) - positive_count,
        positives_missed_by_retrieval=positives_missed,
        positives_excluded_existing_link=len(existing_positive_links),
        positives_excluded_host=len(host_positive_links - existing_positive_links),
        distance_counts=dict(sorted(distance_counts.items())),
        distance_positive_counts=dict(sorted(distance_positive_counts.items())),
    )
    return LinkCandidateResult(candidates=candidates, stats=stats)


def build_shared_guest_heuristic_link_candidates(
    *,
    cutoff_at: datetime,
    horizon_days: int = 90,
    active_podcasts_only: bool = True,
    exclude_hosts: bool = True,
    min_podcast_guest_count: int = 1,
    min_shared_guests: int = 1,
    top_per_podcast: int = 5000,
    always_keep_score: int = 0,
) -> LinkCandidateResult:
    """Build deterministic candidates from shared-guest podcast neighborhoods.

    The resulting pairs are a scored subset of degree-3 bipartite candidates:
    target podcast -> prior target guest -> similar podcast -> candidate guest.
    """
    if horizon_days < 1:
        raise ValueError("horizon_days must be at least 1")
    if min_shared_guests < 1:
        raise ValueError("min_shared_guests must be at least 1")
    if top_per_podcast < 0:
        raise ValueError("top_per_podcast must be non-negative")
    if always_keep_score < 0:
        raise ValueError("always_keep_score must be non-negative")

    horizon_end = cutoff_at + timedelta(days=horizon_days)
    historical = build_historical_link_data(cutoff_at=cutoff_at)
    future_positive_links = future_guest_links(cutoff_at=cutoff_at, horizon_end=horizon_end)
    podcast_guest_counts = Counter(
        podcast_id for podcast_id, _canonical_id in historical.existing_guest_links
    )
    podcast_ids = podcasts_to_score(
        active_only=active_podcasts_only,
        available_podcast_ids=historical.podcast_ids,
        podcast_guest_counts=podcast_guest_counts,
        min_guest_count=min_podcast_guest_count,
    )

    candidates: list[LinkCandidate] = []
    distance_counts: Counter[int] = Counter()
    distance_positive_counts: Counter[int] = Counter()
    seen_pairs: set[tuple[int, str]] = set()
    for podcast_id in sorted(podcast_ids):
        target_guests = historical.podcast_guest_ids.get(podcast_id, set())
        if not target_guests:
            continue

        shared_podcast_counts: Counter[int] = Counter()
        for target_guest_id in target_guests:
            for neighbor_podcast_id in historical.guest_podcast_ids.get(target_guest_id, set()):
                if neighbor_podcast_id != podcast_id:
                    shared_podcast_counts[neighbor_podcast_id] += 1

        candidate_scores: Counter[str] = Counter()
        for neighbor_podcast_id, shared_guest_count in shared_podcast_counts.items():
            if shared_guest_count < min_shared_guests:
                continue
            for candidate_id in historical.podcast_guest_ids.get(neighbor_podcast_id, set()):
                candidate_scores[candidate_id] += shared_guest_count

        ranked_candidates = sorted(
            candidate_scores.items(),
            key=lambda item: (-item[1], item[0]),
        )
        if top_per_podcast and always_keep_score:
            top_candidates = ranked_candidates[:top_per_podcast]
            strong_candidates = [
                item for item in ranked_candidates[top_per_podcast:] if item[1] >= always_keep_score
            ]
            ranked_candidates = top_candidates + strong_candidates
        elif top_per_podcast:
            ranked_candidates = ranked_candidates[:top_per_podcast]
        elif always_keep_score:
            ranked_candidates = [item for item in ranked_candidates if item[1] >= always_keep_score]

        for canonical_id, score in ranked_candidates:
            pair = (podcast_id, canonical_id)
            if pair in seen_pairs or pair in historical.existing_guest_links:
                continue
            if exclude_hosts and pair in historical.host_links:
                continue
            seen_pairs.add(pair)
            label = int(pair in future_positive_links)
            candidates.append(
                LinkCandidate(
                    cutoff_at=cutoff_at,
                    horizon_end=horizon_end,
                    podcast_id=podcast_id,
                    canonical_id=canonical_id,
                    distance=3,
                    label=label,
                    retrieval_score=float(score),
                )
            )
            distance_counts[3] += 1
            if label:
                distance_positive_counts[3] += 1

    stats = candidate_stats(
        cutoff_at=cutoff_at,
        horizon_end=horizon_end,
        max_degree=3,
        podcast_count=len(podcast_ids),
        person_count=len(historical.guest_canonical_ids),
        train_edge_count=len(historical.existing_guest_links),
        future_positive_links=future_positive_links,
        existing_guest_links=historical.existing_guest_links,
        host_links=historical.host_links if exclude_hosts else set(),
        candidates=candidates,
        distance_counts=distance_counts,
        distance_positive_counts=distance_positive_counts,
    )
    return LinkCandidateResult(candidates=candidates, stats=stats)


def candidate_stats(
    *,
    cutoff_at: datetime,
    horizon_end: datetime,
    max_degree: int,
    podcast_count: int,
    person_count: int,
    train_edge_count: int,
    future_positive_links: set[tuple[int, str]],
    existing_guest_links: set[tuple[int, str]],
    host_links: set[tuple[int, str]],
    candidates: list[LinkCandidate],
    distance_counts: Counter[int],
    distance_positive_counts: Counter[int],
) -> LinkCandidateStats:
    candidate_pairs = {(candidate.podcast_id, candidate.canonical_id) for candidate in candidates}
    existing_positive_links = future_positive_links & existing_guest_links
    host_positive_links = future_positive_links & host_links
    positive_count = sum(candidate.label for candidate in candidates)
    positives_missed = len(
        future_positive_links
        - candidate_pairs
        - existing_positive_links
        - host_positive_links
    )
    return LinkCandidateStats(
        cutoff_at=cutoff_at,
        horizon_end=horizon_end,
        max_degree=max_degree,
        podcast_count=podcast_count,
        person_count=person_count,
        train_edge_count=train_edge_count,
        future_positive_count=len(future_positive_links),
        candidate_count=len(candidates),
        positive_count=positive_count,
        negative_count=len(candidates) - positive_count,
        positives_missed_by_retrieval=positives_missed,
        positives_excluded_existing_link=len(existing_positive_links),
        positives_excluded_host=len(host_positive_links - existing_positive_links),
        distance_counts=dict(sorted(distance_counts.items())),
        distance_positive_counts=dict(sorted(distance_positive_counts.items())),
    )


def build_historical_link_data(
    *,
    cutoff_at: datetime,
    link_created_before: datetime | None = None,
) -> HistoricalLinkData:
    graph = nx.Graph()
    existing_guest_links: set[tuple[int, str]] = set()
    host_links: set[tuple[int, str]] = set()
    podcast_ids: set[int] = set()
    guest_canonical_ids: set[str] = set()
    podcast_guest_ids: dict[int, set[str]] = {}
    guest_podcast_ids: dict[str, set[int]] = {}
    podcast_host_ids: dict[int, set[str]] = {}
    person_podcast_ids: dict[str, set[int]] = {}
    links = PersonEntityLink.objects.filter(
        observation__role__in=[Appearance.Role.GUEST, Appearance.Role.HOST],
        observation__episode__published_at__lt=cutoff_at,
    )
    if link_created_before is not None:
        links = links.filter(created_at__lt=link_created_before)
    rows = (
        links.exclude(observation__episode__published_at__isnull=True)
        .values_list(
            "observation__podcast_id",
            "canonical_id",
            "observation__role",
        )
        .distinct()
    )
    for podcast_id, canonical_id, role in rows.iterator(chunk_size=20_000):
        podcast_node: PodcastNode = ("podcast", podcast_id)
        person_node: PersonNode = ("person", canonical_id)
        graph.add_edge(podcast_node, person_node)
        podcast_ids.add(podcast_id)
        person_podcast_ids.setdefault(canonical_id, set()).add(podcast_id)
        pair = (podcast_id, canonical_id)
        if role == Appearance.Role.GUEST:
            existing_guest_links.add(pair)
            guest_canonical_ids.add(canonical_id)
            podcast_guest_ids.setdefault(podcast_id, set()).add(canonical_id)
            guest_podcast_ids.setdefault(canonical_id, set()).add(podcast_id)
        else:
            host_links.add(pair)
            podcast_host_ids.setdefault(podcast_id, set()).add(canonical_id)
    return HistoricalLinkData(
        graph=graph,
        existing_guest_links=existing_guest_links,
        host_links=host_links,
        podcast_ids=podcast_ids,
        guest_canonical_ids=guest_canonical_ids,
        podcast_guest_ids=podcast_guest_ids,
        guest_podcast_ids=guest_podcast_ids,
        podcast_host_ids=podcast_host_ids,
        person_podcast_ids=person_podcast_ids,
    )


def future_guest_links(*, cutoff_at: datetime, horizon_end: datetime) -> set[tuple[int, str]]:
    rows = (
        PersonEntityLink.objects.filter(
            observation__role=Appearance.Role.GUEST,
            observation__episode__published_at__gte=cutoff_at,
            observation__episode__published_at__lt=horizon_end,
        )
        .exclude(observation__episode__published_at__isnull=True)
        .values_list("observation__podcast_id", "canonical_id")
        .distinct()
    )
    return set(rows.iterator(chunk_size=20_000))


def podcasts_to_score(
    *,
    active_only: bool,
    available_podcast_ids: set[int],
    podcast_guest_counts: Counter[int],
    min_guest_count: int,
) -> set[int]:
    podcast_ids = set(available_podcast_ids)
    if active_only:
        podcast_ids &= set(Podcast.objects.filter(active=True).values_list("id", flat=True))
    if min_guest_count > 0:
        podcast_ids = {
            podcast_id
            for podcast_id in podcast_ids
            if podcast_guest_counts.get(podcast_id, 0) >= min_guest_count
        }
    return podcast_ids


def podcast_eligibility_stats(
    *,
    cutoff_at: datetime,
    active_only: bool = True,
    min_guest_count: int = 1,
) -> PodcastEligibilityStats:
    historical = build_historical_link_data(cutoff_at=cutoff_at)
    podcast_guest_counts = Counter(
        podcast_id for podcast_id, _canonical_id in historical.existing_guest_links
    )
    active_podcast_ids = set(Podcast.objects.filter(active=True).values_list("id", flat=True))
    scored_podcast_ids = podcasts_to_score(
        active_only=active_only,
        available_podcast_ids=historical.podcast_ids,
        podcast_guest_counts=podcast_guest_counts,
        min_guest_count=min_guest_count,
    )
    return PodcastEligibilityStats(
        total_podcasts=Podcast.objects.count(),
        active_podcasts=len(active_podcast_ids),
        historical_linked_podcasts=len(historical.podcast_ids),
        active_historical_linked_podcasts=len(active_podcast_ids & historical.podcast_ids),
        scored_podcasts=len(scored_podcast_ids),
        inactive_historical_linked_podcasts=len(historical.podcast_ids - active_podcast_ids),
        active_without_historical_links=len(active_podcast_ids - historical.podcast_ids),
    )


def compare_candidate_sets(
    *,
    baseline: LinkCandidateResult,
    heuristic: LinkCandidateResult,
) -> CandidateSetComparison:
    baseline_positive_pairs = {
        (candidate.podcast_id, candidate.canonical_id)
        for candidate in baseline.candidates
        if candidate.label
    }
    heuristic_positive_pairs = {
        (candidate.podcast_id, candidate.canonical_id)
        for candidate in heuristic.candidates
        if candidate.label
    }
    return CandidateSetComparison(
        baseline_candidate_count=baseline.stats.candidate_count,
        heuristic_candidate_count=heuristic.stats.candidate_count,
        baseline_positive_count=baseline.stats.positive_count,
        heuristic_positive_count=heuristic.stats.positive_count,
        positives_lost_from_baseline=len(baseline_positive_pairs - heuristic_positive_pairs),
        positives_added_outside_baseline=len(heuristic_positive_pairs - baseline_positive_pairs),
    )


def latest_cutoff_for_labeling(*, horizon_days: int) -> datetime | None:
    latest_published_at = (
        PersonEntityLink.objects.exclude(observation__episode__published_at__isnull=True)
        .order_by("-observation__episode__published_at")
        .values_list("observation__episode__published_at", flat=True)
        .first()
    )
    if latest_published_at is None:
        return None
    return latest_published_at - timedelta(days=horizon_days)


def format_podcast_eligibility_stats(stats: PodcastEligibilityStats) -> list[str]:
    return [
        f"Total podcasts: {stats.total_podcasts:,}",
        f"Active podcasts: {stats.active_podcasts:,}",
        f"Podcasts with any historical canonical link: {stats.historical_linked_podcasts:,}",
        "Active podcasts with historical canonical links: "
        f"{stats.active_historical_linked_podcasts:,}",
        f"Scored podcasts after min guest filter: {stats.scored_podcasts:,}",
        "Inactive podcasts with historical canonical links: "
        f"{stats.inactive_historical_linked_podcasts:,}",
        "Active podcasts without historical canonical links: "
        f"{stats.active_without_historical_links:,}",
    ]


def format_link_candidate_stats(stats: LinkCandidateStats) -> list[str]:
    imbalance = (
        "undefined"
        if stats.positive_count == 0
        else f"{stats.negative_count / stats.positive_count:,.1f}:1"
    )
    lines = [
        f"Cutoff: {stats.cutoff_at.isoformat()}",
        f"Horizon end: {stats.horizon_end.isoformat()}",
        f"Max degree: {stats.max_degree}",
        f"Podcasts scored: {stats.podcast_count:,}",
        f"Known guest people: {stats.person_count:,}",
        f"Historical guest links: {stats.train_edge_count:,}",
        f"Future positive links in horizon: {stats.future_positive_count:,}",
        f"Candidate rows: {stats.candidate_count:,}",
        f"Positive labels in candidates: {stats.positive_count:,}",
        f"Negative labels in candidates: {stats.negative_count:,}",
        f"Positive rate: {stats.positive_rate:.6f}",
        f"Negative:positive imbalance: {imbalance}",
        f"Retrieval recall over eligible future positives: {stats.retrieval_recall:.3f}",
        f"Future positives missed by degree retrieval: {stats.positives_missed_by_retrieval:,}",
        f"Future positives excluded as existing links: {stats.positives_excluded_existing_link:,}",
        f"Future positives excluded as hosts: {stats.positives_excluded_host:,}",
    ]
    if stats.distance_counts:
        lines.append("Rows by distance:")
        for distance, count in stats.distance_counts.items():
            positives = stats.distance_positive_counts.get(distance, 0)
            positive_rate = positives / count if count else 0.0
            lines.append(
                f"  distance {distance}: {count:,} rows, "
                f"{positives:,} positives, positive_rate={positive_rate:.6f}"
            )
    return lines


def format_candidate_set_comparison(comparison: CandidateSetComparison) -> list[str]:
    return [
        "Heuristic vs degree baseline:",
        f"  baseline rows: {comparison.baseline_candidate_count:,}",
        f"  heuristic rows: {comparison.heuristic_candidate_count:,}",
        f"  row reduction: {comparison.row_reduction:.3f}",
        f"  baseline positives: {comparison.baseline_positive_count:,}",
        f"  heuristic positives: {comparison.heuristic_positive_count:,}",
        f"  positive retention: {comparison.positive_retention:.3f}",
        f"  positives lost from baseline: {comparison.positives_lost_from_baseline:,}",
        f"  positives added outside baseline: {comparison.positives_added_outside_baseline:,}",
    ]
