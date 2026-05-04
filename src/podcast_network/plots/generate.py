from __future__ import annotations

import html
import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path

import networkx as nx
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

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
        ),
        histogram_chart(
            "auth_histogram.svg",
            node_values()["auth"],
            "Authority Distribution",
            "Authority",
            log_x=True,
        ),
        histogram_chart(
            "hub_histogram.svg",
            node_values()["hub"],
            "Hub Distribution",
            "Hub",
            log_x=True,
        ),
        histogram_chart(
            "close_histogram.svg",
            node_values()["closeness"],
            "Closeness Distribution",
            "Closeness",
        ),
        histogram_chart(
            "degree_histogram.svg",
            node_values()["degree_cen"],
            "Degree Centrality Distribution",
            "Degree Centrality",
            log_x=True,
        ),
        histogram_chart(
            "bt_histogram.svg",
            node_values()["betweenness"],
            "Betweenness Distribution",
            "Betweenness",
            log_x=True,
        ),
        histogram_chart(
            "leader_histogram.svg",
            [
                value
                for podcast in repo.podcasts
                for value in (podcast.hub_leader_score, podcast.bt_diff_leader_score)
            ],
            "Podcast Leadership Scores",
            "Score",
        ),
        line_chart(
            "evolution_global.svg",
            evolution_frame(),
            ["num_people", "num_podcasts", "avg_path", "density"],
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
            [prediction.prob for prediction in repo.predictions],
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
        plotly_histogram("pr_histogram.html", values["pr"], "PageRank Distribution"),
        plotly_histogram("auth_histogram.html", values["auth"], "Authority Distribution"),
        plotly_histogram("hub_histogram.html", values["hub"], "Hub Distribution"),
        plotly_histogram("close_histogram.html", values["closeness"], "Closeness Distribution"),
        plotly_histogram(
            "degree_histogram.html",
            values["degree_cen"],
            "Degree Centrality Distribution",
        ),
        plotly_histogram(
            "bt_histogram.html",
            values["betweenness"],
            "Betweenness Distribution",
        ),
        plotly_histogram(
            "leader_histogram.html",
            [
                value
                for podcast in repo.podcasts
                for value in (podcast.hub_leader_score, podcast.bt_diff_leader_score)
            ],
            "Podcast Leadership Scores",
        ),
        plotly_line(
            "evolution_global.html",
            evolution_frame(),
            ["num_people", "num_podcasts"],
            "Network Evolution",
            y_title="Count",
        ),
        plotly_line(
            "evolution_structure.html",
            evolution_frame(),
            ["avg_path", "density", "avg_clust", "transitivity"],
            "Network Structure Evolution",
            y_title="Measure",
        ),
        plotly_line("evolution_pr.html", score_frame("pr_evol.csv"), None, "PageRank Evolution"),
        plotly_line(
            "evolution_authority.html",
            score_frame("auths_evol.csv"),
            None,
            "Authority Evolution",
        ),
        plotly_line("evolution_hub.html", score_frame("hubs_evol.csv"), None, "Hub Evolution"),
        plotly_line(
            "evolution_closeness.html",
            score_frame("close_evol.csv"),
            None,
            "Closeness Evolution",
        ),
        plotly_histogram(
            "predictions_histogram.html",
            [prediction.prob for prediction in repo.predictions],
            "Prediction Probabilities",
        ),
        plotly_network(
            "network_podcasts.html",
            podcast_similarity_graph(),
            "Podcast Similarity Graph",
        ),
        plotly_network("network_people.html", people_graph(repo), "People Graph Sample"),
    ]
    return outputs


def node_values() -> pd.DataFrame:
    return pd.read_csv(LEGACY_ANALYSIS_DIR / "node_values.csv", sep="\t", index_col=0)


def evolution_frame() -> pd.DataFrame:
    return pd.read_csv(LEGACY_ANALYSIS_DIR / "evolution_of_measures.csv", sep="\t", index_col=0)


def score_frame(name: str) -> pd.DataFrame:
    return pd.read_csv(LEGACY_ANALYSIS_DIR / name, sep="\t", index_col=0)


def podcast_category_counts(repo: LegacyRepository) -> dict[str, float]:
    return dict(Counter(podcast.categories[0] for podcast in repo.podcasts if podcast.categories))


def people_category_counts(repo: LegacyRepository) -> dict[str, float]:
    return dict(Counter(person.top_category or "Unknown" for person in repo.people))


def category_bias(repo: LegacyRepository) -> dict[str, float]:
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


def podcast_similarity_graph() -> nx.Graph:
    df = pd.read_csv(LEGACY_ANALYSIS_DIR / "podcast_similarities.csv", sep="\t", index_col=0)
    graph = nx.Graph()
    for row in df.sort_values("score", ascending=False).head(90).itertuples():
        graph.add_edge(row.podcast1, row.podcast2, weight=float(row.score))
    return graph


def people_graph(repo: LegacyRepository) -> nx.Graph:
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


def bar_chart(
    filename: str,
    values: dict[str, float],
    title: str,
    ylabel: str,
    *,
    log_scale: bool = False,
) -> Path:
    items = sorted(values.items(), key=lambda item: item[1], reverse=True)[:14]
    plot_values = (
        [(label, math.log10(value + 1)) for label, value in items]
        if log_scale
        else items
    )
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
    max_count = max(counts) or 1
    bar_w = chart_w / bins
    parts = svg_header(title)
    parts.append(axis(left, top, chart_w, chart_h, xlabel))
    for index, count in enumerate(counts):
        height = (count / max_count) * chart_h
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


def plotly_histogram(filename: str, values: Iterable[float], title: str) -> Path:
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
    return write_plotly(filename, fig)


def plotly_line(
    filename: str,
    frame: pd.DataFrame,
    columns: list[str] | None,
    title: str,
    *,
    y_title: str = "Value",
) -> Path:
    columns = columns or [column for column in frame.columns if column != "dates"][:10]
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
        hover_name="series",
        hover_data={"dates": True, "value": ":.6f", "series": False},
        color_discrete_sequence=PALETTE,
    )
    fig.update_layout(xaxis_title="Date", yaxis_title=y_title, hovermode="x unified")
    return write_plotly(filename, fig)


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
                "Podcast category: %{x}<br>"
                "Guest category: %{y}<br>"
                "Appearances: %{z}<extra></extra>"
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
        text=[
            f"{node}<br>Degree: {graph.degree[node]}"
            for node in nodes
        ],
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


def write_plotly(filename: str, fig: go.Figure) -> Path:
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
    )
    html_text = output.read_text(encoding="utf-8")
    html_text = html_text.replace(
        "<head><meta charset=\"utf-8\" /></head>",
        (
            "<head><meta charset=\"utf-8\" />"
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
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        'role="img">',
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
        f'{text(left + width / 2, top + height + 46, label, 12, "#667085", "middle")}'
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
