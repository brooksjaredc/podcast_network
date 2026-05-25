from __future__ import annotations

import html
import math
from collections.abc import Iterable
from pathlib import Path

import networkx as nx
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from podcast_network.plots.config import HEIGHT, PALETTE, PLOTS_DIR, WIDTH


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
