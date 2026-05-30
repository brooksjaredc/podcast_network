from __future__ import annotations

import gzip
import pickle
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from podcast_network.graph import SixDegreesGraph

GRAPH_ARTIFACT_FORMAT = "podcast-network-six-degrees-graph"
GRAPH_ARTIFACT_VERSION = 1


@dataclass(frozen=True)
class GraphArtifact:
    graph: SixDegreesGraph
    metadata: dict[str, object]


def write_graph_artifact(
    *,
    graph: SixDegreesGraph,
    path: Path,
    metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    payload_metadata = {
        "format": GRAPH_ARTIFACT_FORMAT,
        "format_version": GRAPH_ARTIFACT_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "person_count": graph.person_count,
        "podcast_count": graph.podcast_count,
        **(metadata or {}),
    }
    payload = {
        "metadata": payload_metadata,
        "graph": graph,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb") as file:
        pickle.dump(payload, file, protocol=pickle.HIGHEST_PROTOCOL)
    return payload_metadata


def load_graph_artifact(path: Path) -> GraphArtifact:
    with gzip.open(path, "rb") as file:
        payload = pickle.load(file)
    metadata, graph = graph_artifact_parts(payload)
    return GraphArtifact(graph=graph, metadata=metadata)


def graph_artifact_parts(payload: Any) -> tuple[dict[str, object], SixDegreesGraph]:
    if not isinstance(payload, dict):
        raise ValueError("Graph artifact payload must be a dictionary.")
    metadata = payload.get("metadata")
    graph = payload.get("graph")
    if not isinstance(metadata, dict):
        raise ValueError("Graph artifact metadata must be a dictionary.")
    if metadata.get("format") != GRAPH_ARTIFACT_FORMAT:
        raise ValueError("Graph artifact has an unsupported format.")
    if metadata.get("format_version") != GRAPH_ARTIFACT_VERSION:
        raise ValueError("Graph artifact has an unsupported format version.")
    if not isinstance(graph, SixDegreesGraph):
        raise ValueError("Graph artifact did not contain a SixDegreesGraph.")
    return metadata, graph
