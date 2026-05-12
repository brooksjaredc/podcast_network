from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from itertools import combinations

import networkx as nx
from django.utils import timezone

from podcast_network.web.catalog.models import (
    Appearance,
    NetworkMetricRun,
    PersonEntityLink,
    PersonNetworkMetric,
    PodcastNetworkMetric,
)

GRAPH_VERSION = "network-metrics-v1"
DEFAULT_BETWEENNESS_SAMPLE_SIZE = 1000
DEFAULT_CLOSENESS_SAMPLE_SIZE = 1000


@dataclass
class PersonNodeStats:
    display_name: str
    person_ids: Counter[int] = field(default_factory=Counter)
    guest_appearances: int = 0
    host_appearances: int = 0
    podcast_ids: set[int] = field(default_factory=set)
    latest_episode_at: object | None = None


@dataclass(frozen=True)
class MetricGraphs:
    directed_people: nx.DiGraph
    undirected_people: nx.Graph
    podcast_similarity: nx.Graph
    person_stats: dict[str, PersonNodeStats]


def calculate_and_store_network_metrics() -> NetworkMetricRun:
    run = NetworkMetricRun.objects.create(graph_version=GRAPH_VERSION)
    try:
        graphs = build_metric_graphs()
        person_metrics = person_metric_rows(run=run, graphs=graphs)
        podcast_metrics = podcast_metric_rows(run=run, graph=graphs.podcast_similarity)

        PersonNetworkMetric.objects.bulk_create(person_metrics, batch_size=5000)
        PodcastNetworkMetric.objects.bulk_create(podcast_metrics, batch_size=5000)

        run.person_nodes = graphs.undirected_people.number_of_nodes()
        run.person_edges = graphs.undirected_people.number_of_edges()
        run.podcast_nodes = graphs.podcast_similarity.number_of_nodes()
        run.podcast_edges = graphs.podcast_similarity.number_of_edges()
        run.metadata = {
            **run.metadata,
            "betweenness_sample_size": DEFAULT_BETWEENNESS_SAMPLE_SIZE,
            "closeness_sample_size": DEFAULT_CLOSENESS_SAMPLE_SIZE,
            "person_betweenness_approximate": (
                run.person_nodes > DEFAULT_BETWEENNESS_SAMPLE_SIZE
            ),
            "podcast_betweenness_approximate": (
                run.podcast_nodes > DEFAULT_BETWEENNESS_SAMPLE_SIZE
            ),
            "person_closeness_approximate": (
                run.person_nodes > DEFAULT_CLOSENESS_SAMPLE_SIZE
            ),
            "podcast_closeness_approximate": (
                run.podcast_nodes > DEFAULT_CLOSENESS_SAMPLE_SIZE
            ),
        }
        run.status = NetworkMetricRun.Status.SUCCEEDED
        run.finished_at = timezone.now()
        run.save(
            update_fields=[
                "person_nodes",
                "person_edges",
                "podcast_nodes",
                "podcast_edges",
                "metadata",
                "status",
                "finished_at",
            ]
        )
    except Exception:
        run.status = NetworkMetricRun.Status.FAILED
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "finished_at"])
        raise
    return run


def build_metric_graphs() -> MetricGraphs:
    directed_people = nx.DiGraph()
    undirected_people = nx.Graph()
    podcast_similarity = nx.Graph()
    person_stats: dict[str, PersonNodeStats] = {}
    episode_people: dict[int, dict[str, set[str]]] = defaultdict(
        lambda: {Appearance.Role.GUEST: set(), Appearance.Role.HOST: set()}
    )
    guest_podcasts_by_person: dict[str, set[int]] = defaultdict(set)
    podcast_names: dict[int, str] = {}

    rows = PersonEntityLink.objects.filter(
        observation__role__in=[Appearance.Role.GUEST, Appearance.Role.HOST],
    ).values_list(
        "observation__episode_id",
        "canonical_id",
        "canonical__display_name",
        "observation__person_id",
        "observation__podcast_id",
        "observation__podcast__name",
        "observation__role",
        "observation__episode__published_at",
    )
    for (
        episode_id,
        canonical_id,
        display_name,
        person_id,
        podcast_id,
        podcast_name,
        role,
        published_at,
    ) in rows.iterator(chunk_size=20_000):
        directed_people.add_node(canonical_id)
        undirected_people.add_node(canonical_id)
        stats = person_stats.setdefault(
            canonical_id,
            PersonNodeStats(display_name=display_name),
        )
        stats.person_ids[person_id] += 1
        stats.podcast_ids.add(podcast_id)
        if role == Appearance.Role.GUEST:
            stats.guest_appearances += 1
            guest_podcasts_by_person[canonical_id].add(podcast_id)
        else:
            stats.host_appearances += 1
        if published_at and (
            stats.latest_episode_at is None or published_at > stats.latest_episode_at
        ):
            stats.latest_episode_at = published_at
        episode_people[episode_id][role].add(canonical_id)
        podcast_names[podcast_id] = podcast_name
        podcast_similarity.add_node(podcast_id, name=podcast_name)

    for people_by_role in episode_people.values():
        guests = people_by_role[Appearance.Role.GUEST]
        hosts = people_by_role[Appearance.Role.HOST]
        for guest_id in guests:
            for host_id in hosts:
                if guest_id == host_id:
                    continue
                add_weighted_edge(directed_people, guest_id, host_id)
                add_weighted_edge(undirected_people, guest_id, host_id)

    shared_guest_counts: Counter[tuple[int, int]] = Counter()
    for podcast_ids in guest_podcasts_by_person.values():
        for first_id, second_id in combinations(sorted(podcast_ids), 2):
            shared_guest_counts[(first_id, second_id)] += 1
    for (first_id, second_id), weight in shared_guest_counts.items():
        podcast_similarity.add_edge(first_id, second_id, weight=weight)

    return MetricGraphs(
        directed_people=directed_people,
        undirected_people=undirected_people,
        podcast_similarity=podcast_similarity,
        person_stats=person_stats,
    )


def add_weighted_edge(graph: nx.Graph, source: str, target: str) -> None:
    if graph.has_edge(source, target):
        graph[source][target]["weight"] += 1
    else:
        graph.add_edge(source, target, weight=1)


def person_metric_rows(*, run: NetworkMetricRun, graphs: MetricGraphs) -> list[PersonNetworkMetric]:
    directed = graphs.directed_people
    undirected = graphs.undirected_people
    pagerank = nx.pagerank(directed, weight="weight") if directed else {}
    hubs, authorities = safe_hits(directed)
    closeness = closeness_centrality(undirected)
    betweenness = betweenness_centrality(undirected)
    degree = nx.degree_centrality(undirected) if undirected else {}

    pagerank_ranks = ranks(pagerank)
    hub_ranks = ranks(hubs)
    authority_ranks = ranks(authorities)
    closeness_ranks = ranks(closeness)
    betweenness_ranks = ranks(betweenness)
    degree_ranks = ranks(degree)

    rows = []
    for canonical_id, stats in graphs.person_stats.items():
        rows.append(
            PersonNetworkMetric(
                run=run,
                canonical_id=canonical_id,
                display_name=stats.display_name,
                representative_person_id=representative_person_id(stats),
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
        )
    return rows


def podcast_metric_rows(*, run: NetworkMetricRun, graph: nx.Graph) -> list[PodcastNetworkMetric]:
    closeness = closeness_centrality(graph)
    betweenness = betweenness_centrality(graph)
    degree = nx.degree_centrality(graph) if graph else {}
    closeness_ranks = ranks(closeness)
    betweenness_ranks = ranks(betweenness)
    degree_ranks = ranks(degree)
    return [
        PodcastNetworkMetric(
            run=run,
            podcast_id=podcast_id,
            closeness=closeness.get(podcast_id, 0.0),
            betweenness=betweenness.get(podcast_id, 0.0),
            degree_centrality=degree.get(podcast_id, 0.0),
            closeness_rank=closeness_ranks.get(podcast_id, 0),
            betweenness_rank=betweenness_ranks.get(podcast_id, 0),
            degree_rank=degree_ranks.get(podcast_id, 0),
            shared_guest_edges=graph.degree[podcast_id] if podcast_id in graph else 0,
        )
        for podcast_id in graph.nodes
    ]


def safe_hits(graph: nx.DiGraph) -> tuple[dict[str, float], dict[str, float]]:
    if not graph:
        return {}, {}
    try:
        return nx.hits(graph, max_iter=500, normalized=True)
    except nx.PowerIterationFailedConvergence:
        return nx.hits(graph, max_iter=1000, normalized=True)


def betweenness_centrality(graph: nx.Graph) -> dict[object, float]:
    if not graph:
        return {}
    if graph.number_of_nodes() > DEFAULT_BETWEENNESS_SAMPLE_SIZE:
        return nx.betweenness_centrality(
            graph,
            k=DEFAULT_BETWEENNESS_SAMPLE_SIZE,
            seed=7,
        )
    return nx.betweenness_centrality(graph)


def closeness_centrality(graph: nx.Graph) -> dict[object, float]:
    if not graph:
        return {}
    if graph.number_of_nodes() <= DEFAULT_CLOSENESS_SAMPLE_SIZE:
        return nx.closeness_centrality(graph)

    nodes = sorted(graph.nodes, key=str)
    sample_nodes = nodes[:DEFAULT_CLOSENESS_SAMPLE_SIZE]
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
        node: reachable_counts[node] / distance_sums[node]
        if distance_sums[node]
        else 0.0
        for node in nodes
    }


def ranks(values: dict[object, float]) -> dict[object, int]:
    ordered = sorted(values, key=lambda key: (-values[key], str(key)))
    return {key: index + 1 for index, key in enumerate(ordered)}


def representative_person_id(stats: PersonNodeStats) -> int | None:
    if not stats.person_ids:
        return None
    return stats.person_ids.most_common(1)[0][0]


def latest_succeeded_metric_run() -> NetworkMetricRun | None:
    return (
        NetworkMetricRun.objects.filter(status=NetworkMetricRun.Status.SUCCEEDED)
        .order_by("-finished_at", "-started_at")
        .first()
    )
