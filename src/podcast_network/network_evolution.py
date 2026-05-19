from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from random import Random

import networkx as nx
from django.db import transaction
from django.db.models import Max, Min
from django.utils import timezone

from podcast_network.network_metrics import (
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
DEFAULT_BETWEENNESS_SAMPLE_SIZE = 200
DEFAULT_CLOSENESS_SAMPLE_SIZE = 200


@dataclass
class EvolutionPersonStats:
    display_name: str
    person_ids: Counter[int] = field(default_factory=Counter)
    guest_appearances: int = 0
    host_appearances: int = 0
    podcast_ids: set[int] = field(default_factory=set)
    latest_episode_at: datetime | None = None
    first_seen_at: datetime | None = None


@dataclass(frozen=True)
class EvolutionStats:
    run: NetworkEvolutionRun
    weeks_requested: int = 0
    weeks_calculated: int = 0


@dataclass(frozen=True)
class EvolutionResetStats:
    runs_deleted: int
    snapshots_deleted: int
    person_metrics_deleted: int


@dataclass(frozen=True)
class EvolutionGraphs:
    directed_people: nx.DiGraph
    undirected_people: nx.Graph
    person_stats: dict[str, EvolutionPersonStats]
    podcast_ids: set[int]
    podcast_first_seen_at: dict[int, datetime]
    episode_ids: set[int]
    guest_appearance_count: int
    edge_first_seen_at: dict[tuple[str, str], datetime]


def calculate_network_evolution(
    *,
    start_week: date | None = None,
    through_week: date | None = None,
    bootstrap: bool = False,
    recompute: bool = False,
    max_weeks: int | None = None,
    person_metric_limit: int = DEFAULT_PERSON_METRIC_LIMIT,
    betweenness_sample_size: int = DEFAULT_BETWEENNESS_SAMPLE_SIZE,
    closeness_sample_size: int = DEFAULT_CLOSENESS_SAMPLE_SIZE,
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

        run.weeks_requested = len(weeks)
        run.start_week = weeks[0]
        run.end_week = weeks[-1]
        run.metadata = {
            "bootstrap": bootstrap,
            "recompute": recompute,
            "person_metric_limit": person_metric_limit,
            "betweenness_sample_size": betweenness_sample_size,
            "closeness_sample_size": closeness_sample_size,
        }
        run.save(
            update_fields=[
                "weeks_requested",
                "start_week",
                "end_week",
                "metadata",
            ]
        )

        calculated = 0
        for week in weeks:
            with transaction.atomic():
                snapshot = calculate_week_snapshot(
                    run=run,
                    week_start=week,
                    person_metric_limit=person_metric_limit,
                    betweenness_sample_size=betweenness_sample_size,
                    closeness_sample_size=closeness_sample_size,
                    recompute=recompute,
                )
                if snapshot is not None:
                    calculated += 1
            run.weeks_calculated = calculated
            run.save(update_fields=["weeks_calculated"])

        finish_run(
            run,
            status=NetworkEvolutionRun.Status.SUCCEEDED,
            weeks_requested=len(weeks),
            weeks_calculated=calculated,
            start_week=weeks[0],
            end_week=weeks[-1],
            metadata=run.metadata,
        )
        return EvolutionStats(
            run=run,
            weeks_requested=len(weeks),
            weeks_calculated=calculated,
        )
    except Exception:
        finish_run(run, status=NetworkEvolutionRun.Status.FAILED)
        raise


def reset_network_evolution_tables() -> EvolutionResetStats:
    stats = EvolutionResetStats(
        runs_deleted=NetworkEvolutionRun.objects.count(),
        snapshots_deleted=NetworkEvolutionSnapshot.objects.count(),
        person_metrics_deleted=PersonNetworkEvolutionMetric.objects.count(),
    )
    NetworkEvolutionRun.objects.all().delete()
    return stats


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
    betweenness_sample_size: int,
    closeness_sample_size: int,
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
        episode_count=len(graphs.episode_ids),
        guest_appearance_count=graphs.guest_appearance_count,
        new_person_count=new_person_count(graphs, week_start, cutoff_at),
        new_person_edge_count=new_edge_count(graphs, week_start, cutoff_at),
        new_podcast_count=new_podcast_count(graphs, week_start, cutoff_at),
        largest_component_nodes=component.number_of_nodes(),
        largest_component_edges=component.number_of_edges(),
        density=nx.density(component) if component else 0.0,
        average_clustering=nx.average_clustering(component) if component else 0.0,
        transitivity=nx.transitivity(component) if component else 0.0,
        average_shortest_path_length=average_shortest_path_length(
            component,
            sample_size=closeness_sample_size,
        ),
    )
    person_rows = person_evolution_rows(
        snapshot=snapshot,
        graphs=graphs,
        limit=person_metric_limit,
        betweenness_sample_size=betweenness_sample_size,
        closeness_sample_size=closeness_sample_size,
    )
    PersonNetworkEvolutionMetric.objects.bulk_create(person_rows, batch_size=5000)
    return snapshot


def build_evolution_graphs(*, cutoff_at: datetime) -> EvolutionGraphs:
    directed_people = nx.DiGraph()
    undirected_people = nx.Graph()
    person_stats: dict[str, EvolutionPersonStats] = {}
    podcast_ids: set[int] = set()
    podcast_first_seen_at: dict[int, datetime] = {}
    episode_ids: set[int] = set()
    guest_appearance_count = 0
    edge_first_seen_at: dict[tuple[str, str], datetime] = {}
    current_episode_id = None
    current_episode_at = None
    current_people = empty_episode_people()

    rows = (
        PersonEntityLink.objects.filter(
            observation__role__in=[Appearance.Role.GUEST, Appearance.Role.HOST],
            observation__episode__published_at__lt=cutoff_at,
        )
        .order_by("observation__episode_id")
        .values_list(
            "observation__episode_id",
            "canonical_id",
            "canonical__display_name",
            "observation__person_id",
            "observation__podcast_id",
            "observation__role",
            "observation__episode__published_at",
        )
    )
    for (
        episode_id,
        canonical_id,
        display_name,
        person_id,
        podcast_id,
        role,
        published_at,
    ) in rows.iterator(chunk_size=20_000):
        if current_episode_id is None:
            current_episode_id = episode_id
            current_episode_at = published_at
        elif episode_id != current_episode_id:
            add_evolution_episode_edges(
                directed_people=directed_people,
                undirected_people=undirected_people,
                people_by_role=current_people,
                published_at=current_episode_at,
                edge_first_seen_at=edge_first_seen_at,
            )
            current_episode_id = episode_id
            current_episode_at = published_at
            current_people = empty_episode_people()

        directed_people.add_node(canonical_id)
        undirected_people.add_node(canonical_id)
        episode_ids.add(episode_id)
        stats = person_stats.setdefault(
            canonical_id,
            EvolutionPersonStats(display_name=display_name),
        )
        stats.person_ids[person_id] += 1
        stats.podcast_ids.add(podcast_id)
        if published_at and (
            stats.latest_episode_at is None or published_at > stats.latest_episode_at
        ):
            stats.latest_episode_at = published_at
        if published_at and (stats.first_seen_at is None or published_at < stats.first_seen_at):
            stats.first_seen_at = published_at
        podcast_ids.add(podcast_id)
        if published_at:
            first_podcast_seen_at = podcast_first_seen_at.get(podcast_id)
            if first_podcast_seen_at is None or published_at < first_podcast_seen_at:
                podcast_first_seen_at[podcast_id] = published_at
        current_people[role].add(canonical_id)
        if role == Appearance.Role.GUEST:
            stats.guest_appearances += 1
            guest_appearance_count += 1
        else:
            stats.host_appearances += 1

    if current_episode_id is not None:
        add_evolution_episode_edges(
            directed_people=directed_people,
            undirected_people=undirected_people,
            people_by_role=current_people,
            published_at=current_episode_at,
            edge_first_seen_at=edge_first_seen_at,
        )

    return EvolutionGraphs(
        directed_people=directed_people,
        undirected_people=undirected_people,
        person_stats=person_stats,
        podcast_ids=podcast_ids,
        podcast_first_seen_at=podcast_first_seen_at,
        episode_ids=episode_ids,
        guest_appearance_count=guest_appearance_count,
        edge_first_seen_at=edge_first_seen_at,
    )


def person_evolution_rows(
    *,
    snapshot: NetworkEvolutionSnapshot,
    graphs: EvolutionGraphs,
    limit: int,
    betweenness_sample_size: int,
    closeness_sample_size: int,
) -> list[PersonNetworkEvolutionMetric]:
    directed = graphs.directed_people
    undirected = graphs.undirected_people
    pagerank = nx.pagerank(directed, weight="weight") if directed else {}
    hubs, authorities = safe_hits(directed)
    closeness = closeness_centrality(
        undirected,
        sample_size=closeness_sample_size,
    )
    betweenness = betweenness_centrality(
        undirected,
        sample_size=betweenness_sample_size,
    )
    degree = nx.degree_centrality(undirected) if undirected else {}
    tracked_ids = tracked_person_ids(limit=limit)
    if not tracked_ids:
        tracked_ids = top_metric_ids(
            [pagerank, hubs, authorities, closeness, betweenness, degree],
            limit=limit,
        )
    else:
        tracked_ids |= top_metric_ids(
            [pagerank, hubs, authorities, closeness, betweenness, degree],
            limit=max(10, limit // 4),
        )

    pagerank_ranks = ranks(pagerank)
    hub_ranks = ranks(hubs)
    authority_ranks = ranks(authorities)
    closeness_ranks = ranks(closeness)
    betweenness_ranks = ranks(betweenness)
    degree_ranks = ranks(degree)
    return [
        PersonNetworkEvolutionMetric(
            snapshot=snapshot,
            canonical_id=canonical_id,
            display_name=stats.display_name,
            pagerank=pagerank.get(canonical_id, 0.0),
            hub=hubs.get(canonical_id, 0.0),
            authority=authorities.get(canonical_id, 0.0),
            closeness=closeness.get(canonical_id, 0.0),
            betweenness=betweenness.get(canonical_id, 0.0),
            degree_centrality=degree.get(canonical_id, 0.0),
            pagerank_rank=pagerank_ranks.get(canonical_id, 0),
            hub_rank=hub_ranks.get(canonical_id, 0),
            authority_rank=authority_ranks.get(canonical_id, 0),
            closeness_rank=closeness_ranks.get(canonical_id, 0),
            betweenness_rank=betweenness_ranks.get(canonical_id, 0),
            degree_rank=degree_ranks.get(canonical_id, 0),
            guest_appearances=stats.guest_appearances,
            host_appearances=stats.host_appearances,
            podcast_count=len(stats.podcast_ids),
            latest_episode_at=stats.latest_episode_at,
        )
        for canonical_id in sorted(tracked_ids)
        if (stats := graphs.person_stats.get(canonical_id)) is not None
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
    for rank_field in [
        "pagerank_rank",
        "hub_rank",
        "authority_rank",
        "closeness_rank",
        "betweenness_rank",
        "degree_rank",
    ]:
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


def betweenness_centrality(
    graph: nx.Graph,
    *,
    sample_size: int,
) -> dict[object, float]:
    if not graph:
        return {}
    if sample_size > 0 and graph.number_of_nodes() > sample_size:
        return nx.betweenness_centrality(graph, k=sample_size, seed=7)
    return nx.betweenness_centrality(graph)


def closeness_centrality(
    graph: nx.Graph,
    *,
    sample_size: int,
) -> dict[object, float]:
    if not graph:
        return {}
    if sample_size <= 0 or graph.number_of_nodes() <= sample_size:
        return nx.closeness_centrality(graph)

    nodes = sorted(graph.nodes, key=str)
    sample_nodes = nodes[:sample_size]
    distance_sums: Counter[object] = Counter()
    reachable_counts: Counter[object] = Counter()
    for source in sample_nodes:
        lengths = nx.single_source_shortest_path_length(graph, source)
        for target, distance in lengths.items():
            if target == source:
                continue
            distance_sums[target] += distance
            reachable_counts[target] += 1
    return {
        node: reachable_counts[node] / distance_sums[node] if distance_sums[node] else 0.0
        for node in nodes
    }


def add_evolution_episode_edges(
    *,
    directed_people: nx.DiGraph,
    undirected_people: nx.Graph,
    people_by_role: dict[str, set[str]],
    published_at: datetime | None,
    edge_first_seen_at: dict[tuple[str, str], datetime],
) -> None:
    guests = people_by_role[Appearance.Role.GUEST]
    hosts = people_by_role[Appearance.Role.HOST]
    for guest_id in guests:
        for host_id in hosts:
            if guest_id == host_id:
                continue
            add_weighted_edge(directed_people, guest_id, host_id)
            add_weighted_edge(undirected_people, guest_id, host_id)
            if published_at is None:
                continue
            edge_key = tuple(sorted((guest_id, host_id)))
            first_seen = edge_first_seen_at.get(edge_key)
            if first_seen is None or published_at < first_seen:
                edge_first_seen_at[edge_key] = published_at


def add_weighted_edge(graph: nx.Graph, source: str, target: str) -> None:
    if graph.has_edge(source, target):
        graph[source][target]["weight"] += 1
    else:
        graph.add_edge(source, target, weight=1)


def new_person_count(
    graphs: EvolutionGraphs,
    week_start: date,
    cutoff_at: datetime,
) -> int:
    week_start_at = timezone.make_aware(
        datetime.combine(week_start, time.min),
        timezone.get_current_timezone(),
    )
    return sum(
        1
        for stats in graphs.person_stats.values()
        if stats.first_seen_at is not None and week_start_at <= stats.first_seen_at < cutoff_at
    )


def new_edge_count(
    graphs: EvolutionGraphs,
    week_start: date,
    cutoff_at: datetime,
) -> int:
    week_start_at = timezone.make_aware(
        datetime.combine(week_start, time.min),
        timezone.get_current_timezone(),
    )
    return sum(
        1
        for first_seen_at in graphs.edge_first_seen_at.values()
        if week_start_at <= first_seen_at < cutoff_at
    )


def new_podcast_count(
    graphs: EvolutionGraphs,
    week_start: date,
    cutoff_at: datetime,
) -> int:
    week_start_at = timezone.make_aware(
        datetime.combine(week_start, time.min),
        timezone.get_current_timezone(),
    )
    return sum(
        1
        for first_seen_at in graphs.podcast_first_seen_at.values()
        if week_start_at <= first_seen_at < cutoff_at
    )


def largest_component(graph: nx.Graph) -> nx.Graph:
    if not graph:
        return graph.copy()
    component_nodes = max(nx.connected_components(graph), key=len)
    return graph.subgraph(component_nodes).copy()


def average_shortest_path_length(graph: nx.Graph, *, sample_size: int) -> float:
    if graph.number_of_nodes() <= 1:
        return 0.0
    if sample_size > 0 and graph.number_of_nodes() > sample_size:
        nodes = sorted(graph.nodes, key=str)
        sample_nodes = Random(7).sample(nodes, sample_size)
        total_distance = 0
        reachable_pairs = 0
        for source in sample_nodes:
            lengths = nx.single_source_shortest_path_length(graph, source)
            total_distance += sum(lengths.values())
            reachable_pairs += len(lengths) - 1
        return total_distance / reachable_pairs if reachable_pairs else 0.0
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
