from __future__ import annotations

import html
import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

import networkx as nx
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from django.db import OperationalError, ProgrammingError
from django.db.models import Count, Q

from podcast_network.network_metrics import latest_succeeded_metric_run
from podcast_network.paths import PROJECT_ROOT
from podcast_network.web.catalog.models import (
    Appearance,
    FutureLinkPredictionRun,
    NetworkEvolutionSnapshot,
    PersonNetworkEvolutionMetric,
    PersonNetworkMetric,
    Podcast,
    PodcastNetworkMetric,
)

PLOTS_DIR = PROJECT_ROOT / "static" / "plots"
WIDTH = 920
HEIGHT = 430
PALETTE = [
    "#0f766e",
    "#b45309",
    "#1d4ed8",
    "#be123c",
    "#6d28d9",
    "#15803d",
    "#c2410c",
    "#0369a1",
    "#7c2d12",
    "#4338ca",
]

APPLE_GENRE_NAMES = {
    "26": "Top Podcasts",
    "1301": "Arts",
    "1303": "Comedy",
    "1304": "Education",
    "1305": "Kids & Family",
    "1306": "Music",
    "1309": "TV & Film",
    "1310": "Music",
    "1314": "Religion & Spirituality",
    "1318": "Technology",
    "1321": "Business",
    "1324": "Society & Culture",
    "1325": "Government",
    "1326": "History",
    "1483": "Fiction",
    "1488": "True Crime",
    "1489": "News",
    "1502": "Leisure",
    "1511": "Government",
    "1512": "Health & Fitness",
    "1545": "Sports",
}
SPOTIFY_CATEGORY_NAMES = {
    "arts": "Arts",
    "business": "Business",
    "comedy": "Comedy",
    "education": "Education",
    "fiction": "Fiction",
    "health-fitness": "Health & Fitness",
    "history": "History",
    "kids-family": "Kids & Family",
    "leisure": "Leisure",
    "music": "Music",
    "news": "News",
    "religion-spirituality": "Religion & Spirituality",
    "society-culture": "Society & Culture",
    "sports": "Sports",
    "technology": "Technology",
    "true-crime": "True Crime",
    "tv-film": "TV & Film",
}
NON_CATEGORY_CHART_SOURCES = {
    "genre:26",
    "manual-target-search",
    "spotify:top-podcasts",
    "spotify:trending",
}


def generate_all_plots() -> list[Path]:
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    dataset = PlotDataset.from_database()

    outputs = [
        bar_chart(
            "category_podcasts.svg", dataset.podcast_categories, "Podcast Categories", "Podcasts"
        ),
        bar_chart("category_people.svg", dataset.people_categories, "People Categories", "People"),
        bar_chart(
            "category_bias.svg", dataset.category_bias, "Average Category Guest Mix", "Share"
        ),
        heatmap_chart("category_mixing.svg", dataset.category_mixing, "Category Mixing"),
        histogram_chart(
            "pr_histogram.svg",
            dataset.metric_values["pagerank"],
            "PageRank Distribution",
            "PageRank",
        ),
        histogram_chart(
            "auth_histogram.svg",
            dataset.metric_values["authority"],
            "Authority Distribution",
            "Authority",
        ),
        histogram_chart(
            "hub_histogram.svg", dataset.metric_values["hub"], "Hub Distribution", "Hub"
        ),
        histogram_chart(
            "close_histogram.svg",
            dataset.metric_values["closeness"],
            "Closeness Distribution",
            "Closeness",
        ),
        histogram_chart(
            "degree_histogram.svg",
            dataset.metric_values["degree_centrality"],
            "Degree Centrality Distribution",
            "Degree Centrality",
        ),
        histogram_chart(
            "bt_histogram.svg",
            dataset.metric_values["betweenness"],
            "Betweenness Distribution",
            "Betweenness",
        ),
        histogram_chart(
            "leader_histogram.svg", dataset.leadership_scores, "Podcast Leadership Scores", "Score"
        ),
        line_chart("evolution_global.svg", dataset.evolution_global, None, "Network Evolution"),
        line_chart(
            "evolution_pr.svg", dataset.evolution_metric("pagerank"), None, "PageRank Evolution"
        ),
        line_chart(
            "evolution_authority.svg",
            dataset.evolution_metric("authority"),
            None,
            "Authority Evolution",
        ),
        line_chart("evolution_hub.svg", dataset.evolution_metric("hub"), None, "Hub Evolution"),
        line_chart(
            "evolution_closeness.svg",
            dataset.evolution_metric("closeness"),
            None,
            "Closeness Evolution",
        ),
        histogram_chart(
            "predictions_histogram.svg",
            dataset.prediction_scores,
            "Prediction Probabilities",
            "Predicted Probability",
        ),
        network_chart("network_podcasts.svg", dataset.podcast_graph, "Podcast Similarity Graph"),
        network_chart("network_people.svg", dataset.people_graph, "People Graph Sample"),
    ]
    outputs.extend(generate_interactive_plots(dataset))
    return outputs


def generate_interactive_plots(dataset: PlotDataset) -> list[Path]:
    return [
        plotly_bar(
            "category_podcasts.html", dataset.podcast_categories, "Podcast Categories", "Podcasts"
        ),
        plotly_bar(
            "category_people.html",
            dataset.people_categories,
            "People Categories",
            "People",
            log_y=True,
        ),
        plotly_bar(
            "category_bias.html", dataset.category_bias, "Average Category Guest Mix", "Share"
        ),
        plotly_heatmap("category_mixing.html", dataset.category_mixing, "Category Mixing"),
        plotly_histogram(
            "pr_histogram.html",
            dataset.metric_values["pagerank"],
            "PageRank Distribution",
            log_y=True,
        ),
        plotly_histogram(
            "auth_histogram.html",
            dataset.metric_values["authority"],
            "Authority Distribution",
            log_y=True,
        ),
        plotly_histogram(
            "hub_histogram.html", dataset.metric_values["hub"], "Hub Distribution", log_y=True
        ),
        plotly_histogram(
            "close_histogram.html",
            dataset.metric_values["closeness"],
            "Closeness Distribution",
            log_y=True,
        ),
        plotly_histogram(
            "degree_histogram.html",
            dataset.metric_values["degree_centrality"],
            "Degree Centrality Distribution",
            log_y=True,
        ),
        plotly_histogram(
            "bt_histogram.html",
            dataset.metric_values["betweenness"],
            "Betweenness Distribution",
            log_y=True,
        ),
        plotly_histogram(
            "leader_histogram.html", dataset.leadership_scores, "Podcast Leadership Scores"
        ),
        plotly_line("evolution_global.html", dataset.evolution_global, None, "Network Evolution"),
        plotly_line(
            "evolution_structure.html",
            dataset.evolution_structure,
            None,
            "Network Structure Evolution",
        ),
        plotly_line(
            "evolution_pr.html", dataset.evolution_metric("pagerank"), None, "PageRank Evolution"
        ),
        plotly_line(
            "evolution_authority.html",
            dataset.evolution_metric("authority"),
            None,
            "Authority Evolution",
        ),
        plotly_line("evolution_hub.html", dataset.evolution_metric("hub"), None, "Hub Evolution"),
        plotly_line(
            "evolution_closeness.html",
            dataset.evolution_metric("closeness"),
            None,
            "Closeness Evolution",
        ),
        plotly_histogram(
            "predictions_histogram.html", dataset.prediction_scores, "Prediction Probabilities"
        ),
        plotly_network("network_podcasts.html", dataset.podcast_graph, "Podcast Similarity Graph"),
        plotly_network("network_people.html", dataset.people_graph, "People Graph Sample"),
    ]


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


def bar_chart(
    filename: str,
    values: dict[str, float],
    title: str,
    ylabel: str,
    *,
    log_scale: bool = False,
) -> Path:
    items = sorted(values.items(), key=lambda item: item[1], reverse=True)[:14]
    if not items:
        items = [("No data", 0)]
    plot_values = [(label, math.log10(value + 1)) for label, value in items] if log_scale else items
    max_value = max((value for _label, value in plot_values), default=1) or 1
    left, top, chart_w, chart_h = 80, 70, 760, 270
    bar_w = chart_w / max(len(plot_values), 1)
    parts = svg_header(title)
    parts.append(axis(left, top, chart_w, chart_h, ylabel))
    for index, ((label, raw_value), (_plot_label, value)) in enumerate(
        zip(items, plot_values, strict=True)
    ):
        height = 0 if max_value == 0 else (value / max_value) * chart_h
        x = left + index * bar_w + 8
        y = top + chart_h - height
        parts.append(rect(x, y, max(bar_w - 12, 1), height, PALETTE[index % len(PALETTE)]))
        parts.append(
            text(x + bar_w / 2, top + chart_h + 18, truncate(label, 16), 11, anchor="middle")
        )
        parts.append(text(x + bar_w / 2, y - 6, compact(raw_value), 11, anchor="middle"))
    parts.append("</svg>")
    return write_svg(filename, parts)


def histogram_chart(
    filename: str,
    values: Iterable[float],
    title: str,
    xlabel: str,
    *,
    log_x: bool = False,
    log_y: bool = False,
) -> Path:
    cleaned = [float(value) for value in values if pd.notna(value)]
    cleaned = [value for value in cleaned if value > 0] if log_x else cleaned
    if log_x:
        cleaned = [math.log10(value) for value in cleaned]
        xlabel = f"log10({xlabel})"
    if not cleaned:
        cleaned = [0]
    bins = 24
    lo, hi = min(cleaned), max(cleaned)
    if lo == hi:
        hi = lo + 1
    counts = [0] * bins
    for value in cleaned:
        index = min(int(((value - lo) / (hi - lo)) * bins), bins - 1)
        counts[index] += 1
    plotted_counts = [math.log10(count + 1) for count in counts] if log_y else counts
    max_count = max(plotted_counts) or 1
    left, top, chart_w, chart_h = 80, 70, 760, 270
    bar_w = chart_w / bins
    parts = svg_header(title)
    parts.append(axis(left, top, chart_w, chart_h, xlabel))
    for index, plotted_count in enumerate(plotted_counts):
        height = (plotted_count / max_count) * chart_h
        x = left + index * bar_w
        y = top + chart_h - height
        parts.append(rect(x + 1, y, bar_w - 2, height, PALETTE[index % len(PALETTE)]))
    parts.append("</svg>")
    return write_svg(filename, parts)


def line_chart(
    filename: str,
    frame: pd.DataFrame,
    columns: list[str] | None,
    title: str,
) -> Path:
    columns = columns or [column for column in frame.columns if column != "dates"][:10]
    columns = [column for column in columns if column in frame.columns]
    left, top, chart_w, chart_h = 80, 70, 760, 270
    parts = svg_header(title)
    parts.append(axis(left, top, chart_w, chart_h, "value"))
    if frame.empty or not columns:
        parts.append(text(left + chart_w / 2, top + chart_h / 2, "No data", 14, anchor="middle"))
        parts.append("</svg>")
        return write_svg(filename, parts)
    x_values = list(range(len(frame)))
    for index, column in enumerate(columns):
        raw = [float(value or 0) for value in frame[column].fillna(0)]
        max_value = max(raw) or 1
        min_value = min(raw)
        span = max(max_value - min_value, 1e-12)
        points = []
        for x_index, value in zip(x_values, raw, strict=True):
            x = left + (x_index / max(len(x_values) - 1, 1)) * chart_w
            y = top + chart_h - ((value - min_value) / span) * chart_h
            points.append((x, y))
        color = PALETTE[index % len(PALETTE)]
        parts.append(polyline(points, color))
        parts.append(
            text(left + chart_w + 12, top + 18 + index * 18, truncate(column, 22), 12, color)
        )
    parts.append("</svg>")
    return write_svg(filename, parts)


def heatmap_chart(filename: str, values: dict[tuple[str, str], float], title: str) -> Path:
    categories = sorted({category for pair in values for category in pair})[:10]
    if not categories:
        categories = ["No data"]
    max_value = max(values.values(), default=1) or 1
    cell = 28
    left, top = 190, 80
    parts = svg_header(title, height=520)
    for row, y_category in enumerate(categories):
        parts.append(text(180, top + row * cell + 18, truncate(y_category, 22), 11, anchor="end"))
        parts.append(
            text(left + row * cell + 14, top - 10, truncate(y_category, 10), 10, anchor="middle")
        )
        for col, x_category in enumerate(categories):
            value = values.get((x_category, y_category), 0)
            opacity = 0.08 + 0.92 * (value / max_value)
            parts.append(
                rect(
                    left + col * cell,
                    top + row * cell,
                    cell - 2,
                    cell - 2,
                    f"rgba(15,118,110,{opacity:.3f})",
                )
            )
    parts.append("</svg>")
    return write_svg(filename, parts)


def network_chart(filename: str, graph: nx.Graph, title: str) -> Path:
    if graph.number_of_nodes() == 0:
        return write_svg(
            filename,
            [
                *svg_header(title),
                text(WIDTH / 2, HEIGHT / 2, "No data", 14, anchor="middle"),
                "</svg>",
            ],
        )
    positions = nx.spring_layout(graph, seed=7, iterations=80, weight="weight")
    xs = [point[0] for point in positions.values()]
    ys = [point[1] for point in positions.values()]
    left, top, chart_w, chart_h = 50, 70, 820, 300
    parts = svg_header(title)
    scale_x = make_scaler(min(xs), max(xs), left, left + chart_w)
    scale_y = make_scaler(min(ys), max(ys), top + chart_h, top)
    for source, target in graph.edges:
        x1, y1 = scale_x(positions[source][0]), scale_y(positions[source][1])
        x2, y2 = scale_x(positions[target][0]), scale_y(positions[target][1])
        parts.append(line(x1, y1, x2, y2, "#cbd5e1", 0.55))
    for index, node in enumerate(graph.nodes):
        x, y = scale_x(positions[node][0]), scale_y(positions[node][1])
        degree = graph.degree[node]
        radius = 3 + min(degree, 12) * 0.6
        parts.append(circle(x, y, radius, PALETTE[index % len(PALETTE)]))
        if degree >= 4:
            parts.append(text(x + 7, y - 6, truncate(str(node), 20), 10))
    parts.append("</svg>")
    return write_svg(filename, parts)


def plotly_bar(
    filename: str,
    values: dict[str, float],
    title: str,
    y_label: str,
    *,
    log_y: bool = False,
) -> Path:
    items = sorted(values.items(), key=lambda item: item[1], reverse=True)[:24] or [("No data", 0)]
    frame = pd.DataFrame(items, columns=["name", y_label])
    fig = px.bar(frame, x="name", y=y_label, title=title, color_discrete_sequence=[PALETTE[0]])
    if log_y:
        fig.update_yaxes(type="log")
    fig.update_layout(xaxis_title="", yaxis_title=y_label)
    return write_plotly(filename, fig)


def plotly_histogram(
    filename: str,
    values: Iterable[float],
    title: str,
    *,
    log_y: bool = False,
) -> Path:
    cleaned = [float(value) for value in values if pd.notna(value)]
    if not cleaned:
        cleaned = [0]
    fig = px.histogram(
        pd.DataFrame({"value": cleaned}),
        x="value",
        nbins=40,
        title=title,
        labels={"value": "Value"},
        color_discrete_sequence=[PALETTE[0]],
    )
    fig.update_layout(yaxis_title="Count")
    if log_y:
        fig.update_yaxes(type="log")
    return write_plotly(filename, fig)


def plotly_line(
    filename: str,
    frame: pd.DataFrame,
    columns: list[str] | None,
    title: str,
) -> Path:
    columns = columns or [column for column in frame.columns if column != "dates"][:10]
    columns = [column for column in columns if column in frame.columns]
    if frame.empty or not columns:
        fig = go.Figure()
        fig.update_layout(title=title, annotations=[{"text": "No data", "showarrow": False}])
        return write_plotly(filename, fig)
    long_frame = frame[["dates", *columns]].melt(
        id_vars="dates",
        var_name="series",
        value_name="value",
    )
    fig = px.line(
        long_frame,
        x="dates",
        y="value",
        color="series",
        title=title,
        color_discrete_sequence=PALETTE,
    )
    fig.update_traces(hovertemplate="%{fullData.name}<extra></extra>")
    fig.update_layout(xaxis_title="Date", yaxis_title="Value", hovermode="x unified")
    return write_plotly(filename, fig)


def plotly_heatmap(filename: str, values: dict[tuple[str, str], float], title: str) -> Path:
    categories = sorted({category for pair in values for category in pair})[:16] or ["No data"]
    z_values = [
        [values.get((x_category, y_category), 0) for x_category in categories]
        for y_category in categories
    ]
    fig = go.Figure(
        data=go.Heatmap(
            z=z_values,
            x=categories,
            y=categories,
            colorscale="Teal",
            hovertemplate=(
                "Podcast category: %{x}<br>Guest category: %{y}<br>Appearances: %{z}<extra></extra>"
            ),
        )
    )
    fig.update_layout(title=title, xaxis_title="Podcast category", yaxis_title="Guest category")
    return write_plotly(filename, fig)


def plotly_network(filename: str, graph: nx.Graph, title: str) -> Path:
    if graph.number_of_nodes() == 0:
        fig = go.Figure()
        fig.update_layout(title=title, annotations=[{"text": "No data", "showarrow": False}])
        return write_plotly(filename, fig)
    positions = nx.spring_layout(graph, seed=7, iterations=80, weight="weight")
    edge_x = []
    edge_y = []
    for source, target in graph.edges:
        edge_x.extend([positions[source][0], positions[target][0], None])
        edge_y.extend([positions[source][1], positions[target][1], None])
    edge_trace = go.Scatter(
        x=edge_x,
        y=edge_y,
        mode="lines",
        line={"width": 0.5, "color": "#cbd5e1"},
        hoverinfo="skip",
    )
    nodes = list(graph.nodes)
    node_trace = go.Scatter(
        x=[positions[node][0] for node in nodes],
        y=[positions[node][1] for node in nodes],
        mode="markers",
        marker={
            "size": [8 + min(graph.degree[node], 20) for node in nodes],
            "color": [graph.degree[node] for node in nodes],
            "colorscale": "Teal",
            "showscale": True,
            "colorbar": {"title": "Degree"},
            "line": {"width": 0.5, "color": "#ffffff"},
        },
        text=[f"{node}<br>Degree: {graph.degree[node]}" for node in nodes],
        hovertemplate="%{text}<extra></extra>",
    )
    fig = go.Figure(data=[edge_trace, node_trace])
    fig.update_layout(
        title=title, showlegend=False, xaxis={"visible": False}, yaxis={"visible": False}
    )
    return write_plotly(filename, fig)


def write_plotly(filename: str, fig: go.Figure) -> Path:
    output = PLOTS_DIR / filename
    fig.update_layout(
        template="plotly_white",
        autosize=True,
        margin={"l": 58, "r": 32, "t": 92, "b": 64},
        font={"family": "system-ui, sans-serif", "color": "#1f2937"},
        hoverlabel={"align": "left", "font": {"family": "system-ui, sans-serif", "size": 13}},
    )
    fig.write_html(
        output,
        include_plotlyjs="directory",
        full_html=True,
        div_id=plotly_div_id(filename),
        config={"displaylogo": False, "responsive": True},
    )
    html_text = output.read_text(encoding="utf-8")
    html_text = html_text.replace(
        '<head><meta charset="utf-8" /></head>',
        (
            '<head><meta charset="utf-8" />'
            "<style>"
            "html,body{margin:0;padding:10px 4px 0 4px;overflow:hidden;}"
            ".plotly-graph-div{height:calc(100vh - 10px)!important;}"
            "</style></head>"
        ),
    )
    output.write_text(html_text, encoding="utf-8")
    return output


def plotly_div_id(filename: str) -> str:
    stem = Path(filename).stem.replace("_", "-")
    return f"podcast-network-{stem}"


def svg_header(title: str, *, width: int = WIDTH, height: int = HEIGHT) -> list[str]:
    svg_open = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
    )
    return [
        svg_open,
        '<rect width="100%" height="100%" fill="white"/>',
        text(width / 2, 34, title, 20, "#111827", anchor="middle", weight="700"),
    ]


def axis(left: float, top: float, width: float, height: float, label: str) -> str:
    return (
        f'<g stroke="#94a3b8" stroke-width="1">'
        f'<line x1="{left}" y1="{top + height}" x2="{left + width}" y2="{top + height}"/>'
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + height}"/>'
        f"</g>{text(left + width / 2, top + height + 52, label, 12, '#475569', anchor='middle')}"
    )


def write_svg(filename: str, parts: list[str]) -> Path:
    output = PLOTS_DIR / filename
    output.write_text("\n".join(parts), encoding="utf-8")
    return output


def rect(x: float, y: float, width: float, height: float, fill: str) -> str:
    return (
        f'<rect x="{x:.2f}" y="{y:.2f}" width="{width:.2f}" height="{height:.2f}" fill="{fill}"/>'
    )


def circle(x: float, y: float, radius: float, fill: str) -> str:
    return f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius:.2f}" fill="{fill}" opacity="0.88"/>'


def line(x1: float, y1: float, x2: float, y2: float, color: str, opacity: float = 1) -> str:
    return (
        f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
        f'stroke="{color}" stroke-width="1" opacity="{opacity:.2f}"/>'
    )


def polyline(points: list[tuple[float, float]], color: str) -> str:
    if not points:
        return ""
    path = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    return f'<polyline points="{path}" fill="none" stroke="{color}" stroke-width="2.2"/>'


def text(
    x: float,
    y: float,
    value: str,
    size: int,
    color: str = "#1f2937",
    *,
    anchor: str = "start",
    weight: str = "400",
) -> str:
    return (
        f'<text x="{x:.2f}" y="{y:.2f}" fill="{color}" font-size="{size}" '
        f'font-family="system-ui, sans-serif" font-weight="{weight}" text-anchor="{anchor}">'
        f"{html.escape(str(value))}</text>"
    )


def make_scaler(source_min: float, source_max: float, target_min: float, target_max: float):
    if source_min == source_max:
        return lambda _value: (target_min + target_max) / 2
    span = source_max - source_min
    target_span = target_max - target_min
    return lambda value: target_min + ((value - source_min) / span) * target_span


def truncate(value: str, length: int) -> str:
    text_value = str(value)
    if len(text_value) <= length:
        return text_value
    return text_value[: max(length - 3, 0)].rstrip() + "..."


def compact(value: float) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}k"
    if isinstance(value, float) and not value.is_integer():
        return f"{value:.2f}"
    return str(int(value))
