from __future__ import annotations

from django.urls import reverse

from podcast_network.graph import SixDegreesGraph
from podcast_network.graph.six_degrees import PathMessagePart


def link_path_message_parts(
    graph: SixDegreesGraph,
    parts: tuple[PathMessagePart, ...],
) -> tuple[dict[str, str], ...]:
    return tuple(link_path_message_part(graph, part) for part in parts)


def link_path_message_part(graph: SixDegreesGraph, part: PathMessagePart) -> dict[str, str]:
    linked_part = {
        "text": part.text,
        "kind": part.kind,
        "href": "",
    }
    if part.kind == "person" and part.text in graph.person_ids:
        linked_part["href"] = reverse(
            "explorer:person_detail",
            args=[graph.person_ids[part.text]],
        )
    elif part.kind == "podcast" and part.text in graph.podcast_ids:
        linked_part["href"] = reverse(
            "explorer:podcast_detail",
            args=[graph.podcast_ids[part.text]],
        )
    return linked_part
