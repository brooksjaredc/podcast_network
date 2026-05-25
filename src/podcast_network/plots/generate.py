from __future__ import annotations

from pathlib import Path

from podcast_network.plots import renderers
from podcast_network.plots.config import PLOTS_DIR
from podcast_network.plots.data import PlotDataset
from podcast_network.plots.renderers import (
    bar_chart,
    heatmap_chart,
    histogram_chart,
    line_chart,
    network_chart,
    plotly_bar,
    plotly_div_id,
    plotly_heatmap,
    plotly_histogram,
    plotly_line,
    plotly_network,
)

__all__ = [
    "generate_all_plots",
    "generate_interactive_plots",
    "generate_static_plots",
    "plotly_div_id",
]


def generate_all_plots() -> list[Path]:
    renderers.PLOTS_DIR = PLOTS_DIR
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    dataset = PlotDataset.from_database()
    outputs = generate_static_plots(dataset)
    outputs.extend(generate_interactive_plots(dataset))
    return outputs


def generate_static_plots(dataset: PlotDataset) -> list[Path]:
    return [
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
