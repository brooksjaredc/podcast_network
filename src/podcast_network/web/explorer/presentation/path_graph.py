from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from podcast_network.graph import SixDegreesGraph
from podcast_network.graph.six_degrees import PathResult


def build_path_graph(
    graph: SixDegreesGraph,
    result: PathResult,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any] | None:
    if not result.found:
        return None

    horizontal_gap = 180
    left_padding = 90
    width = max(720, left_padding * 2 + horizontal_gap * max(len(result.path) - 1, 1))
    nodes = path_nodes(graph=graph, path=result.path, left_padding=left_padding, gap=horizontal_gap)
    edges = path_edges(
        graph=graph,
        nodes=nodes,
        path=result.path,
        start_date=start_date,
        end_date=end_date,
    )
    return {
        "width": width,
        "height": 260,
        "nodes": nodes,
        "edges": edges,
    }


def path_nodes(
    *,
    graph: SixDegreesGraph,
    path: Sequence[str],
    left_padding: int,
    gap: int,
) -> list[dict[str, Any]]:
    nodes = []
    for index, name in enumerate(path):
        kind = "person" if name in graph.names else "podcast"
        nodes.append(
            {
                "name": name,
                "kind": kind,
                "x": left_padding + index * gap,
                "y": 82 if kind == "person" else 178,
                "label_lines": label_lines(name),
            }
        )
    return nodes


def path_edges(
    *,
    graph: SixDegreesGraph,
    nodes: list[dict[str, Any]],
    path: Sequence[str],
    start_date: str | None,
    end_date: str | None,
) -> list[dict[str, Any]]:
    edges = []
    for index, left in enumerate(path[:-1]):
        right = path[index + 1]
        left_node = nodes[index]
        right_node = nodes[index + 1]
        role = graph.edge_kind(left, right)
        date = graph.edge_date_for_window(
            left,
            right,
            start_date=start_date,
            end_date=end_date,
        )
        edges.append(
            {
                "x1": left_node["x"],
                "y1": left_node["y"],
                "x2": right_node["x"],
                "y2": right_node["y"],
                "path_d": curved_edge_path(
                    left_node["x"],
                    left_node["y"],
                    right_node["x"],
                    right_node["y"],
                ),
                "label": edge_label(role, left_node["kind"], right_node["kind"]),
                "date": date,
                "date_label": edge_date_label(date),
                "label_x": (left_node["x"] + right_node["x"]) / 2,
                "label_y": (left_node["y"] + right_node["y"]) / 2 - 12,
            }
        )
    return edges


def edge_label(role: str, left_kind: str, right_kind: str) -> str:
    if role == "host":
        return "hosts" if left_kind == "person" else "hosted by"
    if left_kind == "person" and right_kind == "podcast":
        return "guest on"
    return "guest"


def edge_date_label(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value[:10])
        return f"{parsed:%b} {parsed.day}, {parsed:%Y}"
    except ValueError:
        return value[:10]


def curved_edge_path(x1: float, y1: float, x2: float, y2: float) -> str:
    control_offset = abs(x2 - x1) * 0.42
    return (
        f"M {x1} {y1} "
        f"C {x1 + control_offset:.1f} {y1}, {x2 - control_offset:.1f} {y2}, {x2} {y2}"
    )


def label_lines(value: str, max_chars: int = 18, max_lines: int = 2) -> list[str]:
    words = value.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
        if len(lines) == max_lines - 1:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if not lines:
        lines = [value[:max_chars]]
    if len(" ".join(words)) > len(" ".join(lines)):
        lines[-1] = truncate_label(lines[-1])
    return lines


def truncate_label(value: str, max_chars: int = 17) -> str:
    if len(value) <= max_chars:
        return value
    return f"{value[: max_chars - 1].rstrip()}..."
