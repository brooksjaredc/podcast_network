from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations

import networkx as nx
import pandas as pd
from django.db import OperationalError, ProgrammingError
from django.db.models import Count, Q

from podcast_network.network.metrics import latest_succeeded_metric_run
from podcast_network.plots.config import (
    APPLE_GENRE_NAMES,
    NON_CATEGORY_CHART_SOURCES,
    SPOTIFY_CATEGORY_NAMES,
)
from podcast_network.web.catalog.models import (
    Appearance,
    FutureLinkPredictionRun,
    NetworkEvolutionSnapshot,
    PersonNetworkEvolutionMetric,
    PersonNetworkMetric,
    Podcast,
    PodcastNetworkMetric,
)


@dataclass(frozen=True)
class PlotDataset:
    podcast_categories: dict[str, float]
    people_categories: dict[str, float]
    category_bias: dict[str, float]
    category_mixing: dict[tuple[str, str], float]
    metric_values: dict[str, list[float]]
    leadership_scores: list[float]
    evolution_global: pd.DataFrame
    evolution_structure: pd.DataFrame
    evolution_metrics: dict[str, pd.DataFrame]
    prediction_scores: list[float]
    podcast_graph: nx.Graph
    people_graph: nx.Graph

    @classmethod
    def from_database(cls) -> PlotDataset:
        try:
            podcast_categories = podcast_category_counts()
            people_categories = people_category_counts()
            category_mixing = category_mixing_counts()
            metric_values = latest_person_metric_values()
            return cls(
                podcast_categories=podcast_categories,
                people_categories=people_categories,
                category_bias=category_guest_mix(podcast_categories=podcast_categories),
                category_mixing=category_mixing,
                metric_values=metric_values,
                leadership_scores=podcast_leadership_scores(),
                evolution_global=evolution_global_frame(),
                evolution_structure=evolution_structure_frame(),
                evolution_metrics=evolution_metric_frames(),
                prediction_scores=prediction_scores(),
                podcast_graph=podcast_similarity_graph(),
                people_graph=people_coappearance_graph(),
            )
        except (OperationalError, ProgrammingError):
            return empty_dataset()

    def evolution_metric(self, metric_name: str) -> pd.DataFrame:
        return self.evolution_metrics.get(metric_name, empty_frame(["dates", "No data"]))


def empty_dataset() -> PlotDataset:
    metric_values = {
        "pagerank": [],
        "authority": [],
        "hub": [],
        "closeness": [],
        "degree_centrality": [],
        "betweenness": [],
    }
    return PlotDataset(
        podcast_categories={},
        people_categories={},
        category_bias={},
        category_mixing={},
        metric_values=metric_values,
        leadership_scores=[],
        evolution_global=empty_frame(["dates", "No data"]),
        evolution_structure=empty_frame(["dates", "No data"]),
        evolution_metrics={key: empty_frame(["dates", "No data"]) for key in metric_values},
        prediction_scores=[],
        podcast_graph=nx.Graph(),
        people_graph=nx.Graph(),
    )


def podcast_category_counts() -> dict[str, float]:
    counts = Counter()
    for metadata in Podcast.objects.values_list("metadata", flat=True).iterator(chunk_size=1000):
        categories = podcast_categories_from_metadata(metadata)
        if categories:
            counts[categories[0]] += 1
    return dict(counts)


def people_category_counts() -> dict[str, float]:
    counts = Counter()
    rows = (
        Appearance.objects.filter(role=Appearance.Role.GUEST)
        .values_list("person_id", "episode__podcast__metadata")
        .iterator(chunk_size=10_000)
    )
    best_by_person: dict[int, Counter[str]] = defaultdict(Counter)
    for person_id, metadata in rows:
        categories = podcast_categories_from_metadata(metadata)
        if categories:
            best_by_person[person_id][categories[0]] += 1
    for category_counts in best_by_person.values():
        category, _count = category_counts.most_common(1)[0]
        counts[category] += 1
    return dict(counts)


def category_guest_mix(*, podcast_categories: dict[str, float]) -> dict[str, float]:
    appearance_counts = Counter()
    rows = (
        Appearance.objects.filter(role=Appearance.Role.GUEST)
        .values_list("episode__podcast__metadata")
        .iterator(chunk_size=10_000)
    )
    for (metadata,) in rows:
        categories = podcast_categories_from_metadata(metadata)
        if categories:
            appearance_counts[categories[0]] += 1
    output = {}
    for category, podcast_count in podcast_categories.items():
        output[category] = appearance_counts.get(category, 0) / max(podcast_count, 1)
    return output


def category_mixing_counts() -> dict[tuple[str, str], float]:
    person_category = primary_person_categories()
    counts = Counter()
    rows = (
        Appearance.objects.filter(role=Appearance.Role.GUEST)
        .values_list("person_id", "episode__podcast__metadata")
        .iterator(chunk_size=10_000)
    )
    for person_id, metadata in rows:
        categories = podcast_categories_from_metadata(metadata)
        guest_category = person_category.get(person_id)
        if categories and guest_category:
            counts[(categories[0], guest_category)] += 1
    return dict(counts)


def primary_person_categories() -> dict[int, str]:
    by_person: dict[int, Counter[str]] = defaultdict(Counter)
    rows = (
        Appearance.objects.filter(role=Appearance.Role.GUEST)
        .values_list("person_id", "episode__podcast__metadata")
        .iterator(chunk_size=10_000)
    )
    for person_id, metadata in rows:
        categories = podcast_categories_from_metadata(metadata)
        if categories:
            by_person[person_id][categories[0]] += 1
    return {
        person_id: counts.most_common(1)[0][0] for person_id, counts in by_person.items() if counts
    }


def podcast_categories_from_metadata(metadata: object) -> list[str]:
    if not isinstance(metadata, dict):
        return []
    categories = []
    legacy = metadata.get("legacy") or {}
    for category in legacy.get("categories") or []:
        append_unique(categories, str(category).strip())
    apple = metadata.get("apple_podcasts") or {}
    for source in apple.get("chart_sources") or []:
        append_unique(categories, category_from_chart_source(source))
    spotify = metadata.get("spotify") or metadata.get("spotify_charts") or {}
    for source in spotify.get("chart_sources") or []:
        append_unique(categories, category_from_chart_source(source))
    return categories


def category_from_chart_source(source: object) -> str:
    text = str(source).strip()
    if not text or text in NON_CATEGORY_CHART_SOURCES:
        return ""
    if text.startswith("genre:"):
        return APPLE_GENRE_NAMES.get(text.split(":", maxsplit=1)[1], "")
    if text.startswith("spotify:"):
        slug = text.split(":", maxsplit=1)[1]
        return SPOTIFY_CATEGORY_NAMES.get(slug, slug.replace("-", " ").title())
    return text


def append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def latest_person_metric_values() -> dict[str, list[float]]:
    values = {
        "pagerank": [],
        "authority": [],
        "hub": [],
        "closeness": [],
        "degree_centrality": [],
        "betweenness": [],
    }
    run = latest_succeeded_metric_run()
    if run is None:
        return values
    rows = PersonNetworkMetric.objects.filter(run=run).values_list(
        "pagerank",
        "authority",
        "hub",
        "closeness",
        "degree_centrality",
        "betweenness",
    )
    for pagerank, authority, hub, closeness, degree, betweenness in rows.iterator(chunk_size=5000):
        values["pagerank"].append(pagerank)
        values["authority"].append(authority)
        values["hub"].append(hub)
        values["closeness"].append(closeness)
        values["degree_centrality"].append(degree)
        values["betweenness"].append(betweenness)
    return values


def podcast_leadership_scores() -> list[float]:
    run = latest_succeeded_metric_run()
    if run is None:
        return []
    rows = PodcastNetworkMetric.objects.filter(run=run).values_list(
        "degree_centrality",
        "shared_guest_edges",
    )
    return [degree * max(shared_edges, 1) for degree, shared_edges in rows]


def evolution_global_frame() -> pd.DataFrame:
    rows = list(
        NetworkEvolutionSnapshot.objects.order_by("week_start").values(
            "week_start",
            "person_nodes",
            "podcast_count",
            "episode_count",
            "guest_appearance_count",
        )
    )
    if not rows:
        return empty_frame(["dates", "People", "Podcasts", "Episodes", "Guest appearances"])
    return pd.DataFrame(
        {
            "dates": [row["week_start"] for row in rows],
            "People": [row["person_nodes"] for row in rows],
            "Podcasts": [row["podcast_count"] for row in rows],
            "Episodes": [row["episode_count"] for row in rows],
            "Guest appearances": [row["guest_appearance_count"] for row in rows],
        }
    )


def evolution_structure_frame() -> pd.DataFrame:
    rows = list(
        NetworkEvolutionSnapshot.objects.order_by("week_start").values(
            "week_start",
            "density",
            "average_clustering",
            "transitivity",
            "average_shortest_path_length",
        )
    )
    if not rows:
        return empty_frame(
            ["dates", "Density", "Average clustering", "Transitivity", "Average path length"]
        )
    return pd.DataFrame(
        {
            "dates": [row["week_start"] for row in rows],
            "Density": [row["density"] for row in rows],
            "Average clustering": [row["average_clustering"] for row in rows],
            "Transitivity": [row["transitivity"] for row in rows],
            "Average path length": [row["average_shortest_path_length"] for row in rows],
        }
    )


def evolution_metric_frames(limit_people: int = 8) -> dict[str, pd.DataFrame]:
    snapshots = list(
        NetworkEvolutionSnapshot.objects.order_by("week_start").values_list("id", "week_start")
    )
    if not snapshots:
        return {}
    latest_snapshot_id = snapshots[-1][0]
    top_names = list(
        PersonNetworkEvolutionMetric.objects.filter(snapshot_id=latest_snapshot_id)
        .order_by("pagerank_rank")
        .values_list("canonical_id", "display_name")[:limit_people]
    )
    metrics = {
        "pagerank": "pagerank",
        "authority": "authority",
        "hub": "hub",
        "closeness": "closeness",
    }
    frames = {}
    for frame_key, field_name in metrics.items():
        series: dict[str, dict[object, float]] = {
            display_name: {} for _canonical_id, display_name in top_names
        }
        rows = PersonNetworkEvolutionMetric.objects.filter(
            canonical_id__in=[canonical_id for canonical_id, _display_name in top_names]
        ).values_list("snapshot__week_start", "canonical_id", "display_name", field_name)
        for week_start, _canonical_id, display_name, value in rows:
            if display_name in series:
                series[display_name][week_start] = value
        frames[frame_key] = pd.DataFrame(
            {
                "dates": [week_start for _snapshot_id, week_start in snapshots],
                **{
                    display_name: [
                        values_by_week.get(week_start, 0.0)
                        for _snapshot_id, week_start in snapshots
                    ]
                    for display_name, values_by_week in series.items()
                },
            }
        )
    return frames


def prediction_scores() -> list[float]:
    run = FutureLinkPredictionRun.objects.order_by("-cutoff_at", "-created_at").first()
    if run is None:
        return []
    return list(run.predictions.values_list("score", flat=True)[:50_000])


def podcast_similarity_graph(limit_podcasts: int = 120, max_edges: int = 500) -> nx.Graph:
    podcast_counts = {
        podcast_id: name
        for podcast_id, name in (
            Podcast.objects.annotate(
                guest_count=Count(
                    "episodes__appearances__person",
                    filter=Q(episodes__appearances__role=Appearance.Role.GUEST),
                    distinct=True,
                )
            )
            .filter(guest_count__gt=0)
            .order_by("-guest_count")
            .values_list("id", "name")[:limit_podcasts]
        )
    }
    podcast_ids = set(podcast_counts)
    graph = nx.Graph()
    for name in podcast_counts.values():
        graph.add_node(name)
    by_person: dict[int, set[int]] = defaultdict(set)
    rows = (
        Appearance.objects.filter(role=Appearance.Role.GUEST, episode__podcast_id__in=podcast_ids)
        .values_list("person_id", "episode__podcast_id")
        .distinct()
    )
    for person_id, podcast_id in rows:
        by_person[person_id].add(podcast_id)
    edge_counts = Counter()
    for podcasts in by_person.values():
        for left, right in combinations(sorted(podcasts), 2):
            edge_counts[(left, right)] += 1
    for (left, right), weight in edge_counts.most_common(max_edges):
        graph.add_edge(podcast_counts[left], podcast_counts[right], weight=weight)
    return graph


def people_coappearance_graph(limit_people: int = 160, max_edges: int = 650) -> nx.Graph:
    top_people = dict(
        Appearance.objects.filter(role=Appearance.Role.GUEST)
        .values("person_id", "person__name")
        .annotate(appearance_count=Count("id"))
        .order_by("-appearance_count", "person__name")[:limit_people]
        .values_list("person_id", "person__name")
    )
    people_ids = set(top_people)
    graph = nx.Graph()
    for person_name in top_people.values():
        graph.add_node(person_name)
    by_podcast: dict[int, set[int]] = defaultdict(set)
    rows = (
        Appearance.objects.filter(role=Appearance.Role.GUEST, person_id__in=people_ids)
        .values_list("episode__podcast_id", "person_id")
        .distinct()
    )
    for podcast_id, person_id in rows:
        by_podcast[podcast_id].add(person_id)
    edge_counts = Counter()
    for people in by_podcast.values():
        for left, right in combinations(sorted(people), 2):
            edge_counts[(left, right)] += 1
    for (left, right), weight in edge_counts.most_common(max_edges):
        graph.add_edge(top_people[left], top_people[right], weight=weight)
    return graph


def empty_frame(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame({column: [] for column in columns})
