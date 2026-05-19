from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import networkx as nx
from django.db import transaction
from django.db.models import Max, Min
from django.utils import timezone

from podcast_network.network_metrics import (
    add_episode_edges,
    closeness_centrality,
    empty_episode_people,
    ranks,
    safe_hits,
)
from podcast_network.web.catalog.models import (
    Appearance,
    Episode,
    NetworkEvolutionRun,
    NetworkEvolutionSnapshot,
    PersonEntityLink,
    PersonNetworkEvolutionMetric,
    PersonNetworkMetric,
)

GRAPH_VERSION = "network-evolution-v1"
DEFAULT_PERSON_METRIC_LIMIT = 100


@dataclass(frozen=True)
class EvolutionStats:
    run: NetworkEvolutionRun
    weeks_requested: int = 0
    weeks_calculated: int = 0


@dataclass(frozen=True)
class EvolutionGraphs:
    directed_people: nx.DiGraph
    undirected_people: nx.Graph
    display_names: dict[str, str]
    podcast_ids: set[int]
    guest_appearance_count: int


def calculate_network_evolution(
    *,
    start_week: date | None = None,
    through_week: date | None = None,
    bootstrap: bool = False,
    recompute: bool = False,
    max_weeks: int | None = None,
    person_metric_limit: int = DEFAULT_PERSON_METRIC_LIMIT,
) -> EvolutionStats:
    run = NetworkEvolutionRun.objects.create(graph_version=GRAPH_VERSION)
    try:
        weeks = missing_evolution_weeks(
            start_week=start_week,
            through_week=through_week,
            bootstrap=bootstrap,
            recompute=recompute,
            max_weeks=max_weeks,
        )
        if not weeks:
            finish_run(
                run,
                status=NetworkEvolutionRun.Status.SKIPPED,
                weeks_requested=0,
                weeks_calculated=0,
                metadata={
                    "reason": (
                        "no_missing_weeks"
                        if latest_snapshot_week() is not None or bootstrap
                        else "bootstrap_required"
                    ),
                    "bootstrap": bootstrap,
                    "recompute": recompute,
                },
            )
            return EvolutionStats(run=run)

        calculated = 0
        with transaction.atomic():
            for week in weeks:
                snapshot = calculate_week_snapshot(
                    run=run,
                    week_start=week,
                    person_metric_limit=person_metric_limit,
                    recompute=recompute,
                )
                if snapshot is not None:
                    calculated += 1

        finish_run(
            run,
            status=NetworkEvolutionRun.Status.SUCCEEDED,
            weeks_requested=len(weeks),
            weeks_calculated=calculated,
            start_week=weeks[0],
            end_week=weeks[-1],
            metadata={
                "bootstrap": bootstrap,
                "recompute": recompute,
                "person_metric_limit": person_metric_limit,
            },
        )
        return EvolutionStats(
            run=run,
            weeks_requested=len(weeks),
            weeks_calculated=calculated,
        )
    except Exception:
        finish_run(run, status=NetworkEvolutionRun.Status.FAILED)
        raise


def missing_evolution_weeks(
    *,
    start_week: date | None,
    through_week: date | None,
    bootstrap: bool,
    recompute: bool,
    max_weeks: int | None,
) -> list[date]:
    first_episode_week, latest_episode_week = episode_week_bounds()
    if latest_episode_week is None:
        return []

    through_week = latest_episode_week if through_week is None else week_floor(through_week)

    if start_week is None:
        latest_stored = latest_snapshot_week()
        if latest_stored is not None and not recompute:
            start_week = latest_stored + timedelta(days=7)
        elif bootstrap and first_episode_week is not None:
            start_week = first_episode_week
        else:
            return []
    else:
        start_week = week_floor(start_week)

    if start_week > through_week:
        return []

    existing = set(
        NetworkEvolutionSnapshot.objects.filter(
            week_start__gte=start_week,
            week_start__lte=through_week,
        ).values_list("week_start", flat=True)
    )
    weeks = []
    current = start_week
    while current <= through_week:
        if recompute or current not in existing:
            weeks.append(current)
        current += timedelta(days=7)
    if max_weeks is not None:
        weeks = weeks[:max_weeks]
    return weeks


def calculate_week_snapshot(
    *,
    run: NetworkEvolutionRun,
    week_start: date,
    person_metric_limit: int,
    recompute: bool,
) -> NetworkEvolutionSnapshot | None:
    if recompute:
        NetworkEvolutionSnapshot.objects.filter(week_start=week_start).delete()
    elif NetworkEvolutionSnapshot.objects.filter(week_start=week_start).exists():
        return None

    cutoff_at = week_cutoff(week_start)
    graphs = build_evolution_graphs(cutoff_at=cutoff_at)
    component = largest_component(graphs.undirected_people)
    snapshot = NetworkEvolutionSnapshot.objects.create(
        run=run,
        week_start=week_start,
        cutoff_at=cutoff_at,
        person_nodes=graphs.undirected_people.number_of_nodes(),
        person_edges=graphs.undirected_people.number_of_edges(),
        podcast_count=len(graphs.podcast_ids),
        guest_appearance_count=graphs.guest_appearance_count,
        largest_component_nodes=component.number_of_nodes(),
        largest_component_edges=component.number_of_edges(),
        density=nx.density(component) if component else 0.0,
        average_clustering=nx.average_clustering(component) if component else 0.0,
        transitivity=nx.transitivity(component) if component else 0.0,
        average_shortest_path_length=average_shortest_path_length(component),
    )
    person_rows = person_evolution_rows(
        snapshot=snapshot,
        graphs=graphs,
        limit=person_metric_limit,
    )
    PersonNetworkEvolutionMetric.objects.bulk_create(person_rows, batch_size=5000)
    return snapshot


def build_evolution_graphs(*, cutoff_at: datetime) -> EvolutionGraphs:
    directed_people = nx.DiGraph()
    undirected_people = nx.Graph()
    display_names: dict[str, str] = {}
    podcast_ids: set[int] = set()
    guest_appearance_count = 0
    current_episode_id = None
    current_people = empty_episode_people()

    rows = PersonEntityLink.objects.filter(
        observation__role__in=[Appearance.Role.GUEST, Appearance.Role.HOST],
        observation__episode__published_at__lt=cutoff_at,
    ).order_by("observation__episode_id").values_list(
        "observation__episode_id",
        "canonical_id",
        "canonical__display_name",
        "observation__podcast_id",
        "observation__role",
    )
    for episode_id, canonical_id, display_name, podcast_id, role in rows.iterator(
        chunk_size=20_000
    ):
        if current_episode_id is None:
            current_episode_id = episode_id
        elif episode_id != current_episode_id:
            add_episode_edges(
                directed_people=directed_people,
                undirected_people=undirected_people,
                people_by_role=current_people,
            )
            current_episode_id = episode_id
            current_people = empty_episode_people()

        directed_people.add_node(canonical_id)
        undirected_people.add_node(canonical_id)
        display_names[canonical_id] = display_name
        podcast_ids.add(podcast_id)
        current_people[role].add(canonical_id)
        if role == Appearance.Role.GUEST:
            guest_appearance_count += 1

    if current_episode_id is not None:
        add_episode_edges(
            directed_people=directed_people,
            undirected_people=undirected_people,
            people_by_role=current_people,
        )

    return EvolutionGraphs(
        directed_people=directed_people,
        undirected_people=undirected_people,
        display_names=display_names,
        podcast_ids=podcast_ids,
        guest_appearance_count=guest_appearance_count,
    )


def person_evolution_rows(
    *,
    snapshot: NetworkEvolutionSnapshot,
    graphs: EvolutionGraphs,
    limit: int,
) -> list[PersonNetworkEvolutionMetric]:
    directed = graphs.directed_people
    undirected = graphs.undirected_people
    pagerank = nx.pagerank(directed, weight="weight") if directed else {}
    hubs, authorities = safe_hits(directed)
    closeness = closeness_centrality(undirected)
    tracked_ids = tracked_person_ids(limit=limit)
    if not tracked_ids:
        tracked_ids = top_metric_ids(
            [pagerank, hubs, authorities, closeness],
            limit=limit,
        )
    else:
        tracked_ids |= top_metric_ids(
            [pagerank, hubs, authorities, closeness],
            limit=max(10, limit // 4),
        )

    pagerank_ranks = ranks(pagerank)
    hub_ranks = ranks(hubs)
    authority_ranks = ranks(authorities)
    closeness_ranks = ranks(closeness)
    return [
        PersonNetworkEvolutionMetric(
            snapshot=snapshot,
            canonical_id=canonical_id,
            display_name=graphs.display_names.get(canonical_id, str(canonical_id)),
            pagerank=pagerank.get(canonical_id, 0.0),
            hub=hubs.get(canonical_id, 0.0),
            authority=authorities.get(canonical_id, 0.0),
            closeness=closeness.get(canonical_id, 0.0),
            pagerank_rank=pagerank_ranks.get(canonical_id, 0),
            hub_rank=hub_ranks.get(canonical_id, 0),
            authority_rank=authority_ranks.get(canonical_id, 0),
            closeness_rank=closeness_ranks.get(canonical_id, 0),
        )
        for canonical_id in sorted(tracked_ids)
        if canonical_id in graphs.display_names
    ]


def tracked_person_ids(*, limit: int) -> set[str]:
    latest_run_id = (
        PersonNetworkMetric.objects.order_by("-run__finished_at", "-run__started_at")
        .values_list("run_id", flat=True)
        .first()
    )
    if latest_run_id is None:
        return set()
    ids: set[str] = set()
    for rank_field in ["pagerank_rank", "hub_rank", "authority_rank", "closeness_rank"]:
        ids.update(
            PersonNetworkMetric.objects.filter(run_id=latest_run_id)
            .order_by(rank_field)
            .values_list("canonical_id", flat=True)[:limit]
        )
    return ids


def top_metric_ids(metrics: list[dict[object, float]], *, limit: int) -> set[str]:
    ids: set[str] = set()
    for metric in metrics:
        ordered = sorted(metric, key=lambda key: (-metric[key], str(key)))[:limit]
        ids.update(str(key) for key in ordered)
    return ids


def largest_component(graph: nx.Graph) -> nx.Graph:
    if not graph:
        return graph.copy()
    component_nodes = max(nx.connected_components(graph), key=len)
    return graph.subgraph(component_nodes).copy()


def average_shortest_path_length(graph: nx.Graph) -> float:
    if graph.number_of_nodes() <= 1:
        return 0.0
    return nx.average_shortest_path_length(graph)


def episode_week_bounds() -> tuple[date | None, date | None]:
    bounds = Episode.objects.filter(published_at__isnull=False).aggregate(
        first=Min("published_at"),
        latest=Max("published_at"),
    )
    first = bounds["first"]
    latest = bounds["latest"]
    return (
        week_floor(first.date()) if first else None,
        week_floor(latest.date()) if latest else None,
    )


def latest_snapshot_week() -> date | None:
    return NetworkEvolutionSnapshot.objects.aggregate(latest=Max("week_start"))["latest"]


def week_floor(value: date) -> date:
    return value - timedelta(days=value.weekday())


def week_cutoff(week_start: date) -> datetime:
    cutoff_date = week_start + timedelta(days=7)
    cutoff = datetime.combine(cutoff_date, time.min)
    return timezone.make_aware(cutoff, timezone.get_current_timezone())


def finish_run(
    run: NetworkEvolutionRun,
    *,
    status: str,
    weeks_requested: int | None = None,
    weeks_calculated: int | None = None,
    start_week: date | None = None,
    end_week: date | None = None,
    metadata: dict[str, object] | None = None,
) -> None:
    run.status = status
    run.finished_at = timezone.now()
    if weeks_requested is not None:
        run.weeks_requested = weeks_requested
    if weeks_calculated is not None:
        run.weeks_calculated = weeks_calculated
    if start_week is not None:
        run.start_week = start_week
    if end_week is not None:
        run.end_week = end_week
    if metadata is not None:
        run.metadata = metadata
    run.save()
