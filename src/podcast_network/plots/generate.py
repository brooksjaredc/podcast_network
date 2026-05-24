from __future__ import annotations

import html
import json
import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from itertools import combinations
from pathlib import Path

import networkx as nx
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from django.apps import apps
from django.db import OperationalError, ProgrammingError

from podcast_network.data import LegacyRepository
from podcast_network.graph.six_degrees import load_edges
from podcast_network.paths import LEGACY_ANALYSIS_DIR, PROJECT_ROOT

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
    "1402": "Design",
    "1459": "Mental Health",
    "1482": "Books",
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
    repo = LegacyRepository()
    outputs = [
        bar_chart(
            "category_podcasts.svg",
            podcast_category_counts(repo),
            "Podcast Categories",
            "Podcasts",
        ),
        bar_chart(
            "category_people.svg",
            people_category_counts(repo),
            "People Categories",
            "People",
            log_scale=True,
        ),
        bar_chart(
            "category_bias.svg",
            category_bias(repo),
            "Average Category Bias",
            "Bias",
        ),
        heatmap_chart(
            "category_mixing.svg",
            category_mixing(repo),
            "Category Mixing",
        ),
        histogram_chart(
            "pr_histogram.svg",
            node_values()["pr"],
            "PageRank Distribution",
            "PageRank",
            log_x=True,
            log_y=True,
        ),
        histogram_chart(
            "auth_histogram.svg",
            node_values()["auth"],
            "Authority Distribution",
            "Authority",
            log_x=True,
            log_y=True,
        ),
        histogram_chart(
            "hub_histogram.svg",
            node_values()["hub"],
            "Hub Distribution",
            "Hub",
            log_x=True,
            log_y=True,
        ),
        histogram_chart(
            "close_histogram.svg",
            node_values()["closeness"],
            "Closeness Distribution",
            "Closeness",
            log_y=True,
        ),
        histogram_chart(
            "degree_histogram.svg",
            node_values()["degree_cen"],
            "Degree Centrality Distribution",
            "Degree Centrality",
            log_x=True,
            log_y=True,
        ),
        histogram_chart(
            "bt_histogram.svg",
            node_values()["betweenness"],
            "Betweenness Distribution",
            "Betweenness",
            log_x=True,
            log_y=True,
        ),
        histogram_chart(
            "leader_histogram.svg",
            leadership_scores(repo),
            "Podcast Leadership Scores",
            "Score",
        ),
        line_chart(
            "evolution_global.svg",
            evolution_frame(),
            ["People", "Podcasts", "Episodes", "Guest appearances"],
            "Network Evolution",
        ),
        line_chart("evolution_pr.svg", score_frame("pr_evol.csv"), None, "PageRank Evolution"),
        line_chart(
            "evolution_authority.svg",
            score_frame("auths_evol.csv"),
            None,
            "Authority Evolution",
        ),
        line_chart("evolution_hub.svg", score_frame("hubs_evol.csv"), None, "Hub Evolution"),
        line_chart(
            "evolution_closeness.svg",
            score_frame("close_evol.csv"),
            None,
            "Closeness Evolution",
        ),
        histogram_chart(
            "predictions_histogram.svg",
            prediction_probabilities(repo),
            "Prediction Probabilities",
            "Predicted Probability",
        ),
        network_chart(
            "network_podcasts.svg",
            podcast_similarity_graph(),
            "Podcast Similarity Graph",
        ),
        network_chart("network_people.svg", people_graph(repo), "People Graph Sample"),
    ]
    outputs.extend(generate_interactive_plots(repo))
    return outputs


def generate_interactive_plots(repo: LegacyRepository) -> list[Path]:
    values = node_values()
    outputs = [
        plotly_bar(
            "category_podcasts.html",
            podcast_category_counts(repo),
            "Podcast Categories",
            "Podcasts",
        ),
        plotly_bar(
            "category_people.html",
            people_category_counts(repo),
            "People Categories",
            "People",
            log_y=True,
        ),
        plotly_bar(
            "category_bias.html",
            category_bias(repo),
            "Average Category Bias",
            "Bias",
        ),
        plotly_heatmap("category_mixing.html", category_mixing(repo), "Category Mixing"),
        plotly_histogram("pr_histogram.html", values["pr"], "PageRank Distribution", log_y=True),
        plotly_histogram(
            "auth_histogram.html",
            values["auth"],
            "Authority Distribution",
            log_y=True,
        ),
        plotly_histogram("hub_histogram.html", values["hub"], "Hub Distribution", log_y=True),
        plotly_histogram(
            "close_histogram.html",
            values["closeness"],
            "Closeness Distribution",
            log_y=True,
        ),
        plotly_histogram(
            "degree_histogram.html",
            values["degree_cen"],
            "Degree Centrality Distribution",
            log_y=True,
        ),
        plotly_histogram(
            "bt_histogram.html",
            values["betweenness"],
            "Betweenness Distribution",
            log_y=True,
        ),
        plotly_histogram(
            "leader_histogram.html",
            leadership_scores(repo),
            "Podcast Leadership Scores",
        ),
        plotly_line(
            "evolution_global.html",
            evolution_frame(),
            ["People", "Podcasts", "Episodes", "Guest appearances"],
            "Network Evolution",
            y_title="Count",
            log_y=True,
        ),
        plotly_line(
            "evolution_structure.html",
            evolution_frame(),
            ["Average path length", "Density", "Clustering", "Transitivity"],
            "Network Structure Evolution",
            y_title="Measure",
        ),
        plotly_line(
            "evolution_pr.html",
            score_frame("pr_evol.csv"),
            None,
            "PageRank Evolution",
            sorted_hover=True,
        ),
        plotly_line(
            "evolution_authority.html",
            score_frame("auths_evol.csv"),
            None,
            "Authority Evolution",
            sorted_hover=True,
        ),
        plotly_line(
            "evolution_hub.html",
            score_frame("hubs_evol.csv"),
            None,
            "Hub Evolution",
            sorted_hover=True,
        ),
        plotly_line(
            "evolution_closeness.html",
            score_frame("close_evol.csv"),
            None,
            "Closeness Evolution",
            sorted_hover=True,
        ),
        plotly_histogram(
            "predictions_histogram.html",
            prediction_probabilities(repo),
            "Prediction Probabilities",
        ),
        cytoscape_network(
            "network_podcasts.html",
            podcast_network_payload(),
            "Podcast Network Graph",
        ),
        cytoscape_network(
            "network_people.html",
            people_network_payload(repo),
            "People Network Graph",
        ),
    ]
    return outputs


def node_values() -> pd.DataFrame:
    try:
        ensure_django_ready()
        from podcast_network.network_metrics import latest_succeeded_metric_run
        from podcast_network.web.catalog.models import PersonNetworkMetric

        run = latest_succeeded_metric_run()
        if run is None:
            return legacy_node_values()
        rows = list(
            PersonNetworkMetric.objects.filter(run=run).values(
                "pagerank",
                "authority",
                "hub",
                "closeness",
                "degree_centrality",
                "betweenness",
            )
        )
    except (OperationalError, ProgrammingError):
        return legacy_node_values()

    if not rows:
        return legacy_node_values()
    frame = pd.DataFrame(rows)
    frame = frame.rename(
        columns={
            "pagerank": "pr",
            "degree_centrality": "degree_cen",
        }
    )
    frame["auth"] = frame["authority"]
    return frame


def legacy_node_values() -> pd.DataFrame:
    return pd.read_csv(LEGACY_ANALYSIS_DIR / "node_values.csv", sep="\t", index_col=0)


def evolution_frame() -> pd.DataFrame:
    ensure_django_ready()
    from podcast_network.web.catalog.models import NetworkEvolutionSnapshot

    rows = list(
        NetworkEvolutionSnapshot.objects.order_by("week_start").values(
            "week_start",
            "person_nodes",
            "person_edges",
            "podcast_count",
            "episode_count",
            "guest_appearance_count",
            "new_person_count",
            "new_person_edge_count",
            "new_podcast_count",
            "largest_component_nodes",
            "largest_component_edges",
            "density",
            "average_clustering",
            "transitivity",
            "average_shortest_path_length",
        )
    )
    if not rows:
        return legacy_evolution_frame()

    frame = pd.DataFrame(rows)
    return pd.DataFrame(
        {
            "dates": pd.to_datetime(frame["week_start"]),
            "People": frame["person_nodes"],
            "Podcasts": frame["podcast_count"],
            "Episodes": frame["episode_count"],
            "Guest appearances": frame["guest_appearance_count"],
            "Person edges": frame["person_edges"],
            "Largest component people": frame["largest_component_nodes"],
            "Largest component edges": frame["largest_component_edges"],
            "New people": frame["new_person_count"],
            "New edges": frame["new_person_edge_count"],
            "New podcasts": frame["new_podcast_count"],
            "Average path length": frame["average_shortest_path_length"],
            "Density": frame["density"],
            "Clustering": frame["average_clustering"],
            "Transitivity": frame["transitivity"],
        }
    )


def score_frame(name: str) -> pd.DataFrame:
    ensure_django_ready()
    from podcast_network.web.catalog.models import (
        NetworkEvolutionSnapshot,
        PersonNetworkEvolutionMetric,
    )

    metric = evolution_metric_name(name)
    value_field = metric
    rank_field = f"{metric}_rank" if metric != "degree_centrality" else "degree_rank"

    latest_snapshot = NetworkEvolutionSnapshot.objects.order_by("-week_start").first()
    if latest_snapshot is None:
        return pd.read_csv(LEGACY_ANALYSIS_DIR / name, sep="\t", index_col=0)

    tracked_ids = list(
        PersonNetworkEvolutionMetric.objects.filter(snapshot=latest_snapshot)
        .order_by(rank_field, "display_name")
        .values_list("canonical_id", flat=True)[:10]
    )
    if not tracked_ids:
        return empty_score_frame()

    rows = list(
        PersonNetworkEvolutionMetric.objects.filter(canonical_id__in=tracked_ids)
        .select_related("snapshot")
        .order_by("snapshot__week_start")
        .values(
            "canonical_id",
            "display_name",
            value_field,
            rank_field,
            "snapshot__week_start",
        )
    )
    if not rows:
        return empty_score_frame()

    long_frame = pd.DataFrame(rows)
    labels = display_labels(long_frame, tracked_ids)
    long_frame["person"] = long_frame["canonical_id"].map(labels)
    long_frame["dates"] = pd.to_datetime(long_frame["snapshot__week_start"])
    pivot = long_frame.pivot_table(
        index="dates",
        columns="person",
        values=value_field,
        aggfunc="first",
    ).reset_index()
    ordered_columns = [
        labels[canonical_id]
        for canonical_id in tracked_ids
        if labels.get(canonical_id) in pivot.columns
    ]
    return pivot[["dates", *ordered_columns]].rename_axis(columns=None)


def legacy_evolution_frame() -> pd.DataFrame:
    frame = pd.read_csv(LEGACY_ANALYSIS_DIR / "evolution_of_measures.csv", sep="\t", index_col=0)
    return frame.rename(
        columns={
            "num_people": "People",
            "num_podcasts": "Podcasts",
            "avg_path": "Average path length",
            "avg_clust": "Clustering",
            "density": "Density",
            "transitivity": "Transitivity",
        }
    )


def evolution_metric_name(name: str) -> str:
    mapping = {
        "pr_evol.csv": "pagerank",
        "auths_evol.csv": "authority",
        "hubs_evol.csv": "hub",
        "close_evol.csv": "closeness",
        "bt_evol.csv": "betweenness",
        "degree_evol.csv": "degree_centrality",
    }
    return mapping.get(name, Path(name).stem)


def empty_score_frame() -> pd.DataFrame:
    return pd.DataFrame({"dates": []})


def ensure_django_ready() -> None:
    if apps.ready:
        return
    import django

    django.setup()


def display_labels(frame: pd.DataFrame, ordered_ids: list[str]) -> dict[str, str]:
    names_by_id = (
        frame.sort_values("snapshot__week_start")
        .groupby("canonical_id")["display_name"]
        .last()
        .to_dict()
    )
    raw_names = [names_by_id.get(canonical_id, canonical_id) for canonical_id in ordered_ids]
    duplicates = {name for name, count in Counter(raw_names).items() if count > 1}
    labels = {}
    for canonical_id in ordered_ids:
        name = names_by_id.get(canonical_id, canonical_id)
        labels[canonical_id] = f"{name} ({canonical_id[-6:]})" if name in duplicates else name
    return labels


def podcast_category_counts(repo: LegacyRepository) -> dict[str, float]:
    counts = database_podcast_category_counts()
    if counts:
        return counts
    return dict(Counter(podcast.categories[0] for podcast in repo.podcasts if podcast.categories))


def people_category_counts(repo: LegacyRepository) -> dict[str, float]:
    counts = database_people_category_counts()
    if counts:
        return counts
    return dict(Counter(person.top_category or "Unknown" for person in repo.people))


def category_bias(repo: LegacyRepository) -> dict[str, float]:
    db_bias = database_category_bias()
    if db_bias:
        return db_bias
    values: dict[str, list[float]] = defaultdict(list)
    for podcast in repo.podcasts:
        if not podcast.categories:
            continue
        try:
            bias = float(podcast.cat_bias)
        except ValueError:
            continue
        values[podcast.categories[0]].append(bias)
    return {
        category: sum(category_values) / len(category_values)
        for category, category_values in values.items()
    }


def category_mixing(repo: LegacyRepository) -> dict[tuple[str, str], float]:
    mixing = database_category_mixing()
    if mixing:
        return mixing
    people_by_name = repo.people_by_name
    podcasts_by_name = repo.podcasts_by_name
    counts: Counter[tuple[str, str]] = Counter()
    for duration in repo.durations:
        person = people_by_name.get(duration.guests)
        podcast = podcasts_by_name.get(duration.podcast)
        if not person or not podcast or not podcast.categories:
            continue
        guest_category = person.top_category or "Unknown"
        podcast_category = podcast.categories[0]
        counts[(podcast_category, guest_category)] += duration.count or 1
    return dict(counts)


def database_podcast_category_counts() -> dict[str, float]:
    try:
        ensure_django_ready()
        from podcast_network.web.catalog.models import Podcast

        counts: Counter[str] = Counter()
        for metadata in Podcast.objects.values_list("metadata", flat=True).iterator(
            chunk_size=2000
        ):
            category = primary_podcast_category(metadata)
            if category:
                counts[category] += 1
    except (OperationalError, ProgrammingError):
        return {}
    return dict(counts)


def database_people_category_counts() -> dict[str, float]:
    top_categories = database_person_top_categories()
    return dict(Counter(top_categories.values()))


def database_category_bias() -> dict[str, float]:
    try:
        ensure_django_ready()
        from podcast_network.web.catalog.models import Podcast

        values: dict[str, list[float]] = defaultdict(list)
        for metadata in Podcast.objects.values_list("metadata", flat=True).iterator(
            chunk_size=2000
        ):
            category = primary_podcast_category(metadata)
            bias = podcast_category_bias(metadata)
            if category and bias is not None:
                values[category].append(bias)
    except (OperationalError, ProgrammingError):
        return {}
    return {
        category: sum(category_values) / len(category_values)
        for category, category_values in values.items()
    }


def database_category_mixing() -> dict[tuple[str, str], float]:
    top_categories = database_person_top_categories()
    if not top_categories:
        return {}
    try:
        ensure_django_ready()
        from podcast_network.web.catalog.models import Appearance

        counts: Counter[tuple[str, str]] = Counter()
        rows = Appearance.objects.filter(role=Appearance.Role.GUEST).values_list(
            "person_id",
            "episode__podcast__metadata",
        )
        for person_id, podcast_metadata in rows.iterator(chunk_size=20_000):
            guest_category = top_categories.get(person_id)
            podcast_category = primary_podcast_category(podcast_metadata)
            if guest_category and podcast_category:
                counts[(podcast_category, guest_category)] += 1
    except (OperationalError, ProgrammingError):
        return {}
    return dict(counts)


def database_person_top_categories() -> dict[int, str]:
    try:
        ensure_django_ready()
        from podcast_network.web.catalog.models import Appearance

        counts_by_person: dict[int, Counter[str]] = defaultdict(Counter)
        rows = Appearance.objects.filter(role=Appearance.Role.GUEST).values_list(
            "person_id",
            "episode__podcast__metadata",
        )
        for person_id, podcast_metadata in rows.iterator(chunk_size=20_000):
            category = primary_podcast_category(podcast_metadata)
            if category:
                counts_by_person[person_id][category] += 1
    except (OperationalError, ProgrammingError):
        return {}
    return {
        person_id: counts.most_common(1)[0][0]
        for person_id, counts in counts_by_person.items()
        if counts
    }


def primary_podcast_category(metadata: object) -> str:
    categories = podcast_categories(metadata)
    return categories[0] if categories else ""


def podcast_categories(metadata: object) -> list[str]:
    if not isinstance(metadata, dict):
        return []

    legacy_categories = metadata.get("legacy", {}).get("categories")
    if isinstance(legacy_categories, list):
        categories = [str(category).strip() for category in legacy_categories if category]
        if categories:
            return unique(categories)

    categories = []
    apple_sources = metadata.get("apple_podcasts", {}).get("chart_sources") or []
    if isinstance(apple_sources, list):
        categories.extend(category_from_chart_source(source) for source in apple_sources)
    spotify_sources = metadata.get("spotify_charts", {}).get("chart_sources") or []
    if isinstance(spotify_sources, list):
        categories.extend(category_from_chart_source(source) for source in spotify_sources)
    return unique(category for category in categories if category)


def category_from_chart_source(source: object) -> str:
    source_text = str(source).strip()
    if not source_text or source_text in NON_CATEGORY_CHART_SOURCES:
        return ""
    if source_text.startswith("genre:"):
        genre_id = source_text.removeprefix("genre:")
        return APPLE_GENRE_NAMES.get(genre_id, f"Apple Genre {genre_id}")
    if source_text.startswith("spotify:"):
        slug = source_text.removeprefix("spotify:")
        return SPOTIFY_CATEGORY_NAMES.get(slug, slug.replace("-", " ").title())
    return ""


def podcast_category_bias(metadata: object) -> float | None:
    if not isinstance(metadata, dict):
        return None
    raw_bias = metadata.get("legacy", {}).get("cat_bias")
    if raw_bias in (None, ""):
        return None
    try:
        return float(raw_bias)
    except (TypeError, ValueError):
        return None


def unique(values: Iterable[str]) -> list[str]:
    output = []
    seen = set()
    for value in values:
        if value not in seen:
            output.append(value)
            seen.add(value)
    return output


def podcast_similarity_graph() -> nx.Graph:
    graph = database_podcast_similarity_graph()
    if graph.number_of_nodes():
        return graph
    if not (LEGACY_ANALYSIS_DIR / "podcast_similarities.csv").exists():
        return nx.Graph()
    df = pd.read_csv(LEGACY_ANALYSIS_DIR / "podcast_similarities.csv", sep="\t", index_col=0)
    graph = nx.Graph()
    for row in df.sort_values("score", ascending=False).head(90).itertuples():
        graph.add_edge(row.podcast1, row.podcast2, weight=float(row.score))
    return graph


def people_graph(repo: LegacyRepository) -> nx.Graph:
    graph = database_people_graph()
    if graph.number_of_nodes():
        return graph
    if not (LEGACY_ANALYSIS_DIR / "six_degrees.edgelist").exists():
        return nx.Graph()
    top_names = {person.name for person in sorted(repo.people, key=lambda item: item.pr_rank)[:180]}
    graph = nx.Graph()
    for edge in load_edges(LEGACY_ANALYSIS_DIR / "six_degrees.edgelist"):
        if edge.left in top_names or edge.right in top_names:
            graph.add_edge(edge.left, edge.right)
    if graph.number_of_nodes() > 240:
        ranked = {person.name: person.pr_rank for person in repo.people}
        keep = sorted(graph.nodes, key=lambda node: ranked.get(node, 999_999))[:240]
        graph = graph.subgraph(keep).copy()
    return graph


def leadership_scores(repo: LegacyRepository) -> list[float]:
    try:
        return [
            value
            for podcast in repo.podcasts
            for value in (podcast.hub_leader_score, podcast.bt_diff_leader_score)
        ]
    except FileNotFoundError:
        return []


def prediction_probabilities(repo: LegacyRepository) -> list[float]:
    try:
        ensure_django_ready()
        from podcast_network.web.catalog.models import FutureLinkPrediction, FutureLinkPredictionRun

        run = FutureLinkPredictionRun.objects.order_by("-created_at").first()
        if run is not None:
            return list(
                FutureLinkPrediction.objects.filter(run=run).values_list("score", flat=True)
            )
    except (OperationalError, ProgrammingError):
        pass
    try:
        return [prediction.prob for prediction in repo.predictions]
    except FileNotFoundError:
        return []


def database_podcast_similarity_graph(*, limit: int = 90) -> nx.Graph:
    graph = nx.Graph()
    try:
        ensure_django_ready()
        from podcast_network.network_metrics import latest_succeeded_metric_run
        from podcast_network.web.catalog.models import PodcastNetworkMetric

        run = latest_succeeded_metric_run()
        if run is None:
            return graph
        metrics = list(
            PodcastNetworkMetric.objects.filter(run=run)
            .select_related("podcast")
            .order_by("degree_rank", "podcast__name")[:limit]
        )
        podcast_ids = {metric.podcast_id for metric in metrics}
        podcast_names = {metric.podcast_id: metric.podcast.name for metric in metrics}
        for metric in metrics:
            graph.add_node(metric.podcast.name)
        edges = (
            PodcastNetworkMetric.objects.filter(run=run, podcast_id__in=podcast_ids)
            .values_list("podcast_id", "podcast__name")
        )
        # The compact SVG uses the same Postgres-backed payload for the interactive graph;
        # this simple graph only needs representative nodes when edge weights are not stored
        # directly in the metric table.
        for _podcast_id, _podcast_name in edges:
            pass
        payload = database_podcast_network_payload(limit=limit, max_edges=180)
        for edge in payload["edges"]:
            source_name = podcast_names.get(int(edge["source"]), edge["source"])
            target_name = podcast_names.get(int(edge["target"]), edge["target"])
            graph.add_edge(source_name, target_name, weight=float(edge["weight"]))
    except (OperationalError, ProgrammingError):
        return nx.Graph()
    return graph


def database_people_graph(*, limit: int = 180) -> nx.Graph:
    graph = nx.Graph()
    try:
        payload = database_people_network_payload(limit=limit, max_edges=300)
        labels = {node["id"]: node["label"] for node in payload["nodes"]}
        for label in labels.values():
            graph.add_node(label)
        for edge in payload["edges"]:
            source = labels.get(edge["source"])
            target = labels.get(edge["target"])
            if source and target:
                graph.add_edge(source, target, weight=float(edge["weight"]))
    except (OperationalError, ProgrammingError):
        return nx.Graph()
    return graph


def podcast_network_payload(*, limit: int = 240, max_edges: int = 750) -> dict:
    payload = database_podcast_network_payload(limit=limit, max_edges=max_edges)
    if payload["nodes"]:
        return payload
    return graph_payload(
        podcast_similarity_graph(),
        title="Podcast Network Graph",
        default_top_n=160,
        default_min_edge=1,
    )


def people_network_payload(
    repo: LegacyRepository, *, limit: int = 240, max_edges: int = 850
) -> dict:
    payload = database_people_network_payload(limit=limit, max_edges=max_edges)
    if payload["nodes"]:
        return payload
    return graph_payload(
        people_graph(repo),
        title="People Network Graph",
        default_top_n=180,
        default_min_edge=1,
    )


def database_podcast_network_payload(*, limit: int, max_edges: int) -> dict:
    try:
        ensure_django_ready()
        from podcast_network.network_metrics import latest_succeeded_metric_run
        from podcast_network.web.catalog.models import (
            Appearance,
            PersonEntityLink,
            PodcastNetworkMetric,
        )

        run = latest_succeeded_metric_run()
        if run is None:
            return empty_network_payload("Podcast Network Graph")
        metrics = list(
            PodcastNetworkMetric.objects.filter(run=run)
            .select_related("podcast")
            .order_by("degree_rank", "podcast__name")[:limit]
        )
        podcast_ids = [metric.podcast_id for metric in metrics]
        podcast_id_set = set(podcast_ids)
        nodes = []
        for metric in metrics:
            nodes.append(
                {
                    "id": str(metric.podcast_id),
                    "label": metric.podcast.name,
                    "displayLabel": metric.podcast.name if metric.degree_rank <= 28 else "",
                    "rank": metric.degree_rank,
                    "score": metric.degree_centrality,
                    "size": 3.5 + min(math.sqrt(metric.shared_guest_edges + 1) * 0.75, 11),
                    "detail": f"shared guest edges: {metric.shared_guest_edges}",
                }
            )

        podcast_ids_by_guest: dict[str, set[int]] = defaultdict(set)
        rows = (
            PersonEntityLink.objects.filter(
                observation__role=Appearance.Role.GUEST,
                observation__podcast_id__in=podcast_id_set,
            )
            .values_list("canonical_id", "observation__podcast_id")
            .distinct()
        )
        for canonical_id, podcast_id in rows.iterator(chunk_size=20_000):
            podcast_ids_by_guest[canonical_id].add(podcast_id)

        edge_counts: Counter[tuple[int, int]] = Counter()
        for shared_podcast_ids in podcast_ids_by_guest.values():
            if len(shared_podcast_ids) < 2:
                continue
            for source, target in combinations(sorted(shared_podcast_ids), 2):
                if source in podcast_id_set and target in podcast_id_set:
                    edge_counts[(source, target)] += 1
        edges = [
            {
                "id": f"{source}-{target}",
                "source": str(source),
                "target": str(target),
                "weight": weight,
                "label": f"{weight} shared guests",
            }
            for (source, target), weight in edge_counts.most_common(max_edges)
        ]
    except (OperationalError, ProgrammingError):
        return empty_network_payload("Podcast Network Graph")

    return network_payload(
        title="Podcast Network Graph",
        nodes=nodes,
        edges=edges,
        default_top_n=180,
        default_min_edge=2,
    )


def database_people_network_payload(*, limit: int, max_edges: int) -> dict:
    try:
        ensure_django_ready()
        from podcast_network.network_metrics import latest_succeeded_metric_run
        from podcast_network.web.catalog.models import (
            Appearance,
            PersonEntityLink,
            PersonNetworkMetric,
        )

        run = latest_succeeded_metric_run()
        if run is None:
            return empty_network_payload("People Network Graph")
        metrics = list(
            PersonNetworkMetric.objects.filter(run=run).order_by("pagerank_rank", "display_name")[
                :limit
            ]
        )
        canonical_ids = [metric.canonical_id for metric in metrics]
        canonical_id_set = set(canonical_ids)
        nodes = []
        for metric in metrics:
            nodes.append(
                {
                    "id": metric.canonical_id,
                    "label": metric.display_name,
                    "displayLabel": metric.display_name if metric.pagerank_rank <= 28 else "",
                    "rank": metric.pagerank_rank,
                    "score": metric.pagerank,
                    "size": 3.5
                    + min(
                        math.sqrt(metric.guest_appearances + metric.host_appearances + 1) * 0.34,
                        12,
                    ),
                    "detail": (
                        f"guest appearances: {metric.guest_appearances} | "
                        f"host appearances: {metric.host_appearances}"
                    ),
                }
            )

        edge_counts: Counter[tuple[str, str]] = Counter()
        current_episode_id = None
        people_by_role = {Appearance.Role.GUEST: set(), Appearance.Role.HOST: set()}
        rows = (
            PersonEntityLink.objects.filter(
                canonical_id__in=canonical_id_set,
                observation__role__in=[Appearance.Role.GUEST, Appearance.Role.HOST],
            )
            .order_by("observation__episode_id")
            .values_list("observation__episode_id", "canonical_id", "observation__role")
        )
        for episode_id, canonical_id, role in rows.iterator(chunk_size=20_000):
            if current_episode_id is None:
                current_episode_id = episode_id
            elif episode_id != current_episode_id:
                add_people_payload_edges(edge_counts, people_by_role)
                current_episode_id = episode_id
                people_by_role = {Appearance.Role.GUEST: set(), Appearance.Role.HOST: set()}
            people_by_role[role].add(canonical_id)
        if current_episode_id is not None:
            add_people_payload_edges(edge_counts, people_by_role)

        edges = [
            {
                "id": f"{source}-{target}",
                "source": source,
                "target": target,
                "weight": weight,
                "label": f"{weight} host/guest links",
            }
            for (source, target), weight in edge_counts.most_common(max_edges)
        ]
    except (OperationalError, ProgrammingError):
        return empty_network_payload("People Network Graph")

    return network_payload(
        title="People Network Graph",
        nodes=nodes,
        edges=edges,
        default_top_n=180,
        default_min_edge=1,
    )


def add_people_payload_edges(
    edge_counts: Counter[tuple[str, str]],
    people_by_role: dict[str, set[str]],
) -> None:
    for guest_id in people_by_role.get("guest", set()):
        for host_id in people_by_role.get("host", set()):
            if guest_id == host_id:
                continue
            edge_counts[tuple(sorted((guest_id, host_id)))] += 1


def graph_payload(
    graph: nx.Graph,
    *,
    title: str,
    default_top_n: int,
    default_min_edge: int,
) -> dict:
    nodes = [
        {
            "id": str(node),
            "label": str(node),
            "displayLabel": str(node) if index < 28 else "",
            "rank": index + 1,
            "score": graph.degree[node],
            "size": 3.5 + min(math.sqrt(graph.degree[node] + 1) * 1.25, 12),
            "detail": f"degree: {graph.degree[node]}",
        }
        for index, node in enumerate(
            sorted(graph.nodes, key=lambda item: graph.degree[item], reverse=True)
        )
    ]
    edges = [
        {
            "id": f"{source}-{target}",
            "source": str(source),
            "target": str(target),
            "weight": float(data.get("weight", 1)),
            "label": f"{compact(float(data.get('weight', 1)))} weight",
        }
        for source, target, data in graph.edges(data=True)
    ]
    return network_payload(
        title=title,
        nodes=nodes,
        edges=edges,
        default_top_n=default_top_n,
        default_min_edge=default_min_edge,
    )


def empty_network_payload(title: str) -> dict:
    return network_payload(title=title, nodes=[], edges=[], default_top_n=0, default_min_edge=1)


def network_payload(
    *,
    title: str,
    nodes: list[dict],
    edges: list[dict],
    default_top_n: int,
    default_min_edge: int,
) -> dict:
    max_edge_weight = max((edge["weight"] for edge in edges), default=1)
    positions = network_positions(nodes, edges, default_top_n, default_min_edge)
    for node in nodes:
        node["color"] = "#2563eb" if node["rank"] <= 25 else "#0f766e"
        node["search"] = node["label"].casefold()
        node["x"] = positions.get(node["id"], (0.0, 0.0))[0]
        node["y"] = positions.get(node["id"], (0.0, 0.0))[1]
    return {
        "title": title,
        "nodes": nodes,
        "edges": edges,
        "maxRank": max((node["rank"] for node in nodes), default=0),
        "maxEdgeWeight": max_edge_weight,
        "defaultTopN": min(default_top_n, len(nodes)),
        "defaultMinEdge": default_min_edge,
    }


def network_positions(
    nodes: list[dict],
    edges: list[dict],
    default_top_n: int,
    default_min_edge: int,
) -> dict[str, tuple[float, float]]:
    visible_ids = {node["id"] for node in nodes if node["rank"] <= default_top_n}
    graph = nx.Graph()
    graph.add_nodes_from(visible_ids)
    graph.add_weighted_edges_from(
        (edge["source"], edge["target"], edge["weight"])
        for edge in edges
        if edge["weight"] >= default_min_edge
        and edge["source"] in visible_ids
        and edge["target"] in visible_ids
    )
    if graph.number_of_edges() == 0:
        return circle_positions([node["id"] for node in nodes])

    core_nodes = {node for edge in graph.edges for node in edge}
    core = graph.subgraph(core_nodes).copy()
    layout = nx.spring_layout(
        core,
        seed=7,
        weight=None,
        k=4.8 / math.sqrt(max(core.number_of_nodes(), 1)),
        iterations=350,
        scale=380,
    )
    positions = balance_component_spacing(
        core,
        {node_id: (float(x), float(y)) for node_id, (x, y) in layout.items()},
        component_spacing=0.62,
        node_spacing=1.75,
    )
    remaining = [node["id"] for node in nodes if node["id"] not in positions]
    positions.update(circle_positions(remaining, radius=430))
    return positions


def balance_component_spacing(
    graph: nx.Graph,
    positions: dict[str, tuple[float, float]],
    *,
    component_spacing: float,
    node_spacing: float,
) -> dict[str, tuple[float, float]]:
    if not positions:
        return positions
    x_center = sum(x for x, _ in positions.values()) / len(positions)
    y_center = sum(y for _, y in positions.values()) / len(positions)
    adjusted = {}
    for component in nx.connected_components(graph):
        component_positions = [positions[node] for node in component if node in positions]
        if not component_positions:
            continue
        component_x = sum(x for x, _ in component_positions) / len(component_positions)
        component_y = sum(y for _, y in component_positions) / len(component_positions)
        target_x = x_center + (component_x - x_center) * component_spacing
        target_y = y_center + (component_y - y_center) * component_spacing
        for node in component:
            if node not in positions:
                continue
            x, y = positions[node]
            adjusted[node] = (
                target_x + (x - component_x) * node_spacing,
                target_y + (y - component_y) * node_spacing,
            )
    return adjusted


def circle_positions(node_ids: list[str], *, radius: float = 360) -> dict[str, tuple[float, float]]:
    if not node_ids:
        return {}
    return {
        node_id: (
            math.cos((index / len(node_ids)) * math.tau) * radius,
            math.sin((index / len(node_ids)) * math.tau) * radius,
        )
        for index, node_id in enumerate(node_ids)
    }


def bar_chart(
    filename: str,
    values: dict[str, float],
    title: str,
    ylabel: str,
    *,
    log_scale: bool = False,
) -> Path:
    items = sorted(values.items(), key=lambda item: item[1], reverse=True)[:14]
    plot_values = [(label, math.log10(value + 1)) for label, value in items] if log_scale else items
    max_value = max((value for _, value in plot_values), default=1)
    left, top, chart_w, chart_h = 80, 70, 760, 270
    bar_w = chart_w / max(len(plot_values), 1)
    parts = svg_header(title)
    parts.append(axis(left, top, chart_w, chart_h, ylabel))
    for index, ((label, raw_value), (_, value)) in enumerate(zip(items, plot_values, strict=True)):
        height = 0 if max_value == 0 else (value / max_value) * chart_h
        x = left + index * bar_w + 8
        y = top + chart_h - height
        color = PALETTE[index % len(PALETTE)]
        parts.append(rect(x, y, bar_w - 12, height, color))
        parts.append(
            text(
                x + bar_w / 2,
                top + chart_h + 18,
                truncate(label, 16),
                11,
                anchor="middle",
            )
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
    cleaned = [float(value) for value in values if pd.notna(value) and float(value) > 0]
    if log_x:
        cleaned = [math.log10(value) for value in cleaned if value > 0]
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
    left, top, chart_w, chart_h = 80, 70, 760, 270
    plotted_counts = [math.log10(count + 1) for count in counts] if log_y else counts
    max_count = max(plotted_counts) or 1
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
    x_values = list(range(len(frame)))
    for index, column in enumerate(columns):
        raw = [float(value) for value in frame[column].fillna(0)]
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
            text(
                left + chart_w + 12,
                top + 18 + index * 18,
                truncate(column, 22),
                12,
                color,
            )
        )
    parts.append("</svg>")
    return write_svg(filename, parts)


def heatmap_chart(filename: str, values: dict[tuple[str, str], float], title: str) -> Path:
    categories = sorted({category for pair in values for category in pair})[:10]
    max_value = max(values.values(), default=1)
    cell = 28
    left, top = 190, 80
    parts = svg_header(title, height=520)
    for row, y_category in enumerate(categories):
        parts.append(text(180, top + row * cell + 18, truncate(y_category, 22), 11, anchor="end"))
        parts.append(
            text(
                left + row * cell + 14,
                top - 10,
                truncate(y_category, 10),
                10,
                anchor="middle",
            )
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
        return write_svg(filename, [*svg_header(title), "</svg>"])
    positions = nx.spring_layout(graph, seed=7, iterations=80)
    xs = [point[0] for point in positions.values()]
    ys = [point[1] for point in positions.values()]
    left, top, chart_w, chart_h = 50, 70, 820, 300
    parts = svg_header(title)
    scale = make_scaler(min(xs), max(xs), left, left + chart_w)
    scale_y = make_scaler(min(ys), max(ys), top + chart_h, top)
    for source, target in graph.edges:
        x1, y1 = scale(positions[source][0]), scale_y(positions[source][1])
        x2, y2 = scale(positions[target][0]), scale_y(positions[target][1])
        parts.append(line(x1, y1, x2, y2, "#cbd5e1", 0.55))
    for index, node in enumerate(graph.nodes):
        x, y = scale(positions[node][0]), scale_y(positions[node][1])
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
    items = sorted(values.items(), key=lambda item: item[1], reverse=True)[:24]
    frame = pd.DataFrame(items, columns=["name", y_label])
    fig = px.bar(
        frame,
        x="name",
        y=y_label,
        title=title,
        hover_data={y_label: ":,.3f"},
        color_discrete_sequence=[PALETTE[0]],
    )
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
    frame = pd.DataFrame({"value": cleaned})
    fig = px.histogram(
        frame,
        x="value",
        nbins=40,
        title=title,
        labels={"value": "Value"},
        hover_data={"value": ":.6f"},
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
    *,
    y_title: str = "Value",
    log_y: bool = False,
    sorted_hover: bool = False,
) -> Path:
    columns = columns or [column for column in frame.columns if column != "dates"][:10]
    columns = [column for column in columns if column in frame.columns]
    if not columns:
        columns = [column for column in frame.columns if column != "dates"][:10]
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
    if sorted_hover:
        fig.update_traces(hoverinfo="none", hovertemplate=None)
    else:
        fig.update_traces(hovertemplate="%{fullData.name}<extra></extra>")
    fig.update_layout(xaxis_title="Date", yaxis_title=y_title, hovermode="x unified")
    if log_y:
        fig.update_yaxes(type="log")
    return write_plotly(
        filename,
        fig,
        post_script=sorted_hover_script(plotly_div_id(filename)) if sorted_hover else None,
    )


def plotly_heatmap(
    filename: str,
    values: dict[tuple[str, str], float],
    title: str,
) -> Path:
    categories = sorted({category for pair in values for category in pair})[:16]
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
        return write_plotly(filename, go.Figure())
    positions = nx.spring_layout(graph, seed=7, iterations=80)
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
        title=title,
        showlegend=False,
        xaxis={"visible": False},
        yaxis={"visible": False},
    )
    return write_plotly(filename, fig)


def cytoscape_network(filename: str, payload: dict, title: str) -> Path:
    output = PLOTS_DIR / filename
    graph_json = json.dumps(payload).replace("</", "<\\/")
    output.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<script src="https://cdn.jsdelivr.net/npm/cytoscape@3.29.2/dist/cytoscape.min.js"></script>
<style>
html,body{{
  margin:0;height:100%;font-family:system-ui,sans-serif;color:#1f2937;
  background:#fff;overflow:hidden;
}}
.network-shell{{height:100%;display:grid;grid-template-rows:auto 1fr;}}
.toolbar{{
  display:flex;align-items:center;gap:12px;padding:10px 12px;
  border-bottom:1px solid #e5e7eb;background:#fff;
}}
.toolbar input[type="search"]{{
  width:220px;max-width:28vw;border:1px solid #cbd5e1;border-radius:6px;
  padding:7px 9px;font:13px system-ui,sans-serif;
}}
.control{{
  display:flex;align-items:center;gap:6px;font-size:12px;color:#475569;
  white-space:nowrap;
}}
.control input[type="range"]{{width:112px;}}
.stat{{margin-left:auto;font-size:12px;color:#64748b;white-space:nowrap;}}
.network-body{{position:relative;min-height:0;}}
#cy{{position:absolute;inset:0;}}
.panel{{
  position:absolute;right:12px;top:12px;width:240px;max-height:calc(100% - 24px);
  overflow:auto;background:rgba(255,255,255,.94);
  border:1px solid rgba(31,41,55,.14);border-radius:8px;
  box-shadow:0 10px 26px rgba(15,23,42,.14);padding:10px;
}}
.panel h2{{font-size:14px;line-height:1.2;margin:0 0 6px 0;}}
.panel p{{font-size:12px;line-height:1.35;margin:4px 0;color:#475569;}}
@media (max-width: 720px){{
  .toolbar{{gap:8px;flex-wrap:wrap;}}
  .toolbar input[type="search"]{{width:100%;max-width:none;}}
  .stat{{margin-left:0;}}
  .panel{{left:8px;right:8px;top:auto;bottom:8px;width:auto;max-height:38%;}}
}}
</style>
</head>
<body>
<div class="network-shell">
  <div class="toolbar">
    <input id="search" type="search" placeholder="Search">
    <label class="control">
      Top <input id="topN" type="range"> <span id="topNValue"></span>
    </label>
    <label class="control">
      Min edge <input id="minEdge" type="range"> <span id="minEdgeValue"></span>
    </label>
    <button id="fit" type="button">Fit</button>
    <span id="stats" class="stat"></span>
  </div>
  <div class="network-body">
    <div id="cy"></div>
    <aside class="panel">
      <h2 id="detailTitle">{html.escape(title)}</h2>
      <p id="detailBody"></p>
    </aside>
  </div>
</div>
<script>
const payload = {graph_json};
const topN = document.getElementById("topN");
const topNValue = document.getElementById("topNValue");
const minEdge = document.getElementById("minEdge");
const minEdgeValue = document.getElementById("minEdgeValue");
const search = document.getElementById("search");
const stats = document.getElementById("stats");
const detailTitle = document.getElementById("detailTitle");
const detailBody = document.getElementById("detailBody");

topN.min = Math.min(25, payload.maxRank || 25);
topN.max = payload.maxRank || 25;
topN.step = 5;
topN.value = payload.defaultTopN || topN.max;
minEdge.min = 1;
minEdge.max = Math.max(1, payload.maxEdgeWeight || 1);
minEdge.step = 1;
minEdge.value = Math.min(payload.defaultMinEdge || 1, minEdge.max);

const cy = cytoscape({{
  container: document.getElementById("cy"),
  wheelSensitivity: 0.18,
  minZoom: 0.15,
  maxZoom: 10,
  style: [
    {{ selector: "node", style: {{
      "background-color": "data(color)",
      "border-color": "#ffffff",
      "border-width": 1,
      "width": "data(renderSize)",
      "height": "data(renderSize)",
      "label": "data(displayLabel)",
      "font-size": "data(renderFontSize)",
      "color": "#334155",
      "text-outline-color": "#ffffff",
      "text-outline-width": "data(renderTextOutlineWidth)",
      "text-max-width": 86,
      "text-wrap": "wrap",
      "text-valign": "bottom",
      "text-margin-y": "data(renderTextMargin)"
    }} }},
    {{ selector: "edge", style: {{
      "line-color": "#64748b",
      "opacity": 0.5,
      "width": `mapData(weight, 1, ${{Math.max(1, payload.maxEdgeWeight || 1)}}, 0.8, 6.5)`,
      "curve-style": "bezier"
    }} }},
    {{ selector: ".faded", style: {{ "opacity": 0.08 }} }},
    {{ selector: ".selected", style: {{
      "border-color": "#111827",
      "border-width": 3,
      "opacity": 1,
      "z-index": 20
    }} }},
    {{ selector: "edge.selected", style: {{
      "line-color": "#111827",
      "opacity": 0.85,
      "width": 1,
      "z-index": 18
    }} }}
  ]
}});

function elementsForFilters() {{
  const rankLimit = Number(topN.value);
  const edgeLimit = Number(minEdge.value);
  const candidateNodes = payload.nodes.filter((node) => node.rank <= rankLimit);
  const candidateNodeIds = new Set(candidateNodes.map((node) => node.id));
  const edges = payload.edges.filter((edge) =>
    edge.weight >= edgeLimit
    && candidateNodeIds.has(edge.source)
    && candidateNodeIds.has(edge.target)
  );
  const connectedNodeIds = new Set(edges.flatMap((edge) => [edge.source, edge.target]));
  const nodes = candidateNodes.filter((node) => connectedNodeIds.has(node.id) || node.rank <= 18);
  return [
    ...nodes.map((node) => ({{
      group: "nodes",
      data: {{
        ...node,
        renderSize: node.size,
        renderFontSize: 8,
        renderTextMargin: 4,
        renderTextOutlineWidth: 1.5
      }},
      position: {{ x: node.x, y: node.y }}
    }})),
    ...edges.map((edge) => ({{ group: "edges", data: edge }}))
  ];
}}

function renderGraph() {{
  topNValue.textContent = topN.value;
  minEdgeValue.textContent = minEdge.value;
  cy.elements().remove();
  cy.add(elementsForFilters());
  cy.layout({{
    name: "preset",
    animate: false
  }}).run();
  window.requestAnimationFrame(() => {{
    cy.fit(undefined, 28);
    syncScreenScale();
  }});
  stats.textContent = `${{cy.nodes().length}} nodes / ${{cy.edges().length}} edges`;
  applySearch();
}}

let scaleSyncQueued = false;
function syncScreenScale() {{
  scaleSyncQueued = false;
  const zoom = Math.max(cy.zoom(), 0.01);
  cy.nodes().forEach((node) => {{
    const baseSize = Number(node.data("size")) || 8;
    node.data({{
      renderSize: clamp(baseSize / zoom, 3.5, 24),
      renderFontSize: clamp(8 / zoom, 4.5, 10),
      renderTextMargin: clamp(4 / zoom, 2, 7),
      renderTextOutlineWidth: clamp(1.5 / zoom, 0.75, 2)
    }});
  }});
}}

function queueScaleSync() {{
  if (scaleSyncQueued) return;
  scaleSyncQueued = true;
  window.requestAnimationFrame(syncScreenScale);
}}

function applySearch() {{
  const query = search.value.trim().toLowerCase();
  cy.elements().removeClass("faded selected");
  if (!query) return;
  const matches = cy.nodes().filter((node) => node.data("search").includes(query));
  if (!matches.length) return;
  cy.elements().addClass("faded");
  matches.removeClass("faded").addClass("selected");
  matches.neighborhood().removeClass("faded").addClass("selected");
  cy.animate({{
    fit: {{ eles: matches.union(matches.neighborhood()), padding: 54 }},
    duration: 180
  }});
}}

cy.on("tap", "node", (event) => {{
  const node = event.target;
  cy.elements().removeClass("faded selected");
  cy.elements().addClass("faded");
  node.removeClass("faded").addClass("selected");
  node.neighborhood().removeClass("faded").addClass("selected");
  detailTitle.textContent = node.data("label");
  detailBody.textContent = `Rank ${{node.data("rank")}} / ${{node.data("detail")}}`;
}});

cy.on("tap", "edge", (event) => {{
  const edge = event.target;
  cy.elements().removeClass("faded selected");
  cy.elements().addClass("faded");
  edge.removeClass("faded").addClass("selected");
  edge.connectedNodes().removeClass("faded").addClass("selected");
  detailTitle.textContent = edge.connectedNodes()
    .map((node) => node.data("label"))
    .join(" - ");
  detailBody.textContent = edge.data("label");
}});

cy.on("tap", (event) => {{
  if (event.target !== cy) return;
  cy.elements().removeClass("faded selected");
  detailTitle.textContent = payload.title;
  detailBody.textContent = "";
}});

document.getElementById("fit").addEventListener("click", () => cy.fit(undefined, 28));
topN.addEventListener("input", renderGraph);
minEdge.addEventListener("input", renderGraph);
search.addEventListener("input", applySearch);
cy.on("zoom", queueScaleSync);
window.addEventListener("resize", () => {{
  cy.resize().fit(undefined, 28);
  queueScaleSync();
}});

function clamp(value, minValue, maxValue) {{
  return Math.max(minValue, Math.min(value, maxValue));
}}

function escapeHtml(value) {{
  return String(value).replace(/[&<>"']/g, (character) => ({{
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  }}[character]));
}}

renderGraph();
</script>
</body>
</html>
""",
        encoding="utf-8",
    )
    return output


def write_plotly(filename: str, fig: go.Figure, *, post_script: str | None = None) -> Path:
    output = PLOTS_DIR / filename
    fig.update_layout(
        template="plotly_white",
        autosize=True,
        margin={"l": 58, "r": 32, "t": 92, "b": 64},
        font={"family": "system-ui, sans-serif", "color": "#1f2937"},
        hoverlabel={
            "align": "left",
            "font": {"family": "system-ui, sans-serif", "size": 13},
        },
    )
    fig.write_html(
        output,
        include_plotlyjs="directory",
        full_html=True,
        div_id=plotly_div_id(filename),
        config={"displaylogo": False, "responsive": True},
        post_script=post_script,
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


def sorted_hover_script(div_id: str) -> str:
    return f"""
(function() {{
  const graph = document.getElementById("{div_id}");
  if (!graph) return;

  const style = document.createElement("style");
  style.textContent = [
    "#{div_id} .hoverlayer .hovertext{{display:none;}}",
    "#{div_id}-sorted-hover{{position:absolute;z-index:20;display:none;",
    "pointer-events:none;background:rgba(255,255,255,0.96);",
    "border:1px solid rgba(31,41,55,0.16);border-radius:6px;",
    "box-shadow:0 10px 28px rgba(15,23,42,0.16);",
    "padding:8px 10px;color:#1f2937;font:13px system-ui,sans-serif;",
    "line-height:1.35;max-width:260px;}}",
    "#{div_id}-sorted-hover .title{{font-weight:600;margin-bottom:5px;}}",
    "#{div_id}-sorted-hover .row{{display:flex;align-items:center;gap:7px;",
    "white-space:nowrap;}}",
    "#{div_id}-sorted-hover .swatch{{width:9px;height:9px;border-radius:999px;",
    "flex:0 0 auto;}}"
  ].join("");
  document.head.appendChild(style);

  const tooltip = document.createElement("div");
  tooltip.id = "{div_id}-sorted-hover";
  graph.parentElement.style.position = graph.parentElement.style.position || "relative";
  graph.parentElement.appendChild(tooltip);

  function formatDate(value) {{
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleDateString(undefined, {{
      year: "numeric",
      month: "short",
      day: "numeric"
    }});
  }}

  function escapeHtml(value) {{
    return String(value).replace(/[&<>"']/g, function(character) {{
      return {{
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
      }}[character];
    }});
  }}

  function colorFor(point) {{
    const color = point.fullData && point.fullData.line && point.fullData.line.color;
    return color || "#64748b";
  }}

  graph.on("plotly_hover", function(eventData) {{
    const points = (eventData.points || [])
      .filter((point) => Number.isFinite(Number(point.y)))
      .sort((left, right) => Number(right.y) - Number(left.y));
    if (!points.length) {{
      tooltip.style.display = "none";
      return;
    }}

    const rows = points.map(function(point) {{
      return "<div class=\\"row\\"><span class=\\"swatch\\" style=\\"background:" +
        escapeHtml(colorFor(point)) + "\\"></span><span>" +
        escapeHtml(point.fullData.name) + "</span></div>";
    }}).join("");
    tooltip.innerHTML = "<div class=\\"title\\">" + formatDate(points[0].x) +
      "</div>" + rows;
    tooltip.style.display = "block";

    const graphRect = graph.getBoundingClientRect();
    const pointer = eventData.event || {{}};
    let left = (pointer.clientX || graphRect.left) - graphRect.left + 14;
    let top = (pointer.clientY || graphRect.top) - graphRect.top + 14;
    const maxLeft = graph.clientWidth - tooltip.offsetWidth - 8;
    const maxTop = graph.clientHeight - tooltip.offsetHeight - 8;
    tooltip.style.left = Math.max(8, Math.min(left, maxLeft)) + "px";
    tooltip.style.top = Math.max(8, Math.min(top, maxTop)) + "px";
  }});

  graph.on("plotly_unhover", function() {{
    tooltip.style.display = "none";
  }});
}})();
"""


def svg_header(title: str, *, width: int = WIDTH, height: int = HEIGHT) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img">',
        f"<title>{html.escape(title)}</title>",
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        text(30, 34, title, 22, "#1f2937"),
    ]


def axis(left: float, top: float, width: float, height: float, label: str) -> str:
    return (
        f'<line x1="{left}" y1="{top + height}" x2="{left + width}" '
        f'y2="{top + height}" stroke="#475467"/>'
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + height}" '
        'stroke="#475467"/>'
        f"{text(left + width / 2, top + height + 46, label, 12, '#667085', 'middle')}"
    )


def write_svg(filename: str, parts: list[str]) -> Path:
    output = PLOTS_DIR / filename
    output.write_text("\n".join(parts), encoding="utf-8")
    return output


def make_scaler(source_min: float, source_max: float, target_min: float, target_max: float):
    span = source_max - source_min or 1

    def scale(value: float) -> float:
        return target_min + ((value - source_min) / span) * (target_max - target_min)

    return scale


def rect(x: float, y: float, width: float, height: float, fill: str) -> str:
    return (
        f'<rect x="{x:.2f}" y="{y:.2f}" width="{max(width, 0):.2f}" '
        f'height="{max(height, 0):.2f}" fill="{fill}"/>'
    )


def line(x1: float, y1: float, x2: float, y2: float, stroke: str, opacity: float = 1) -> str:
    return (
        f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
        f'stroke="{stroke}" stroke-opacity="{opacity:.2f}"/>'
    )


def circle(x: float, y: float, radius: float, fill: str) -> str:
    return f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius:.2f}" fill="{fill}"/>'


def polyline(points: list[tuple[float, float]], stroke: str) -> str:
    encoded = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    return (
        f'<polyline points="{encoded}" fill="none" stroke="{stroke}" '
        'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
    )


def text(
    x: float,
    y: float,
    value: str,
    size: int,
    fill: str = "#344054",
    anchor: str = "start",
) -> str:
    return (
        f'<text x="{x:.2f}" y="{y:.2f}" font-family="system-ui, sans-serif" '
        f'font-size="{size}" fill="{fill}" text-anchor="{anchor}">'
        f"{html.escape(str(value))}</text>"
    )


def truncate(value: str, length: int) -> str:
    return value if len(value) <= length else f"{value[: length - 1]}…"


def compact(value: float) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}m"
    if value >= 1_000:
        return f"{value / 1_000:.1f}k"
    return f"{value:.1f}" if isinstance(value, float) and value % 1 else str(int(value))


if __name__ == "__main__":
    generate_all_plots()
