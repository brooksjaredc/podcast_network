from __future__ import annotations

import ast
import csv
import pickle
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from podcast_network.paths import LEGACY_ANALYSIS_DIR


@dataclass(frozen=True)
class Edge:
    left: str
    right: str
    kind: str


@dataclass(frozen=True)
class PathResult:
    found: bool
    source: str
    target: str
    path: tuple[str, ...]
    message: str
    suggestion: str | None = None

    @property
    def length(self) -> int:
        return max(len(self.path) - 1, 0)


class SixDegreesGraph:
    """In-memory graph for host/guest path queries.

    This intentionally starts without a NetworkX runtime dependency. The old app used NetworkX
    directly inside Django views; this service gives us a small, testable boundary first.
    """

    def __init__(
        self,
        edges: list[Edge],
        names: set[str],
        podcast_ids: dict[str, int] | None = None,
        person_ids: dict[str, int] | None = None,
    ) -> None:
        self.names = names
        self.podcast_ids = podcast_ids or {}
        self.person_ids = person_ids or {}
        self._adjacency: dict[str, dict[str, str]] = {}
        for edge in edges:
            self._adjacency.setdefault(edge.left, {})[edge.right] = edge.kind
            self._adjacency.setdefault(edge.right, {})[edge.left] = edge.kind

    @classmethod
    def from_legacy_dir(cls, data_dir: Path = LEGACY_ANALYSIS_DIR) -> SixDegreesGraph:
        return cls(
            edges=load_edges(data_dir / "six_degrees.edgelist"),
            names=load_names(data_dir / "correct_spellings.csv"),
            podcast_ids=load_pickle(data_dir / "podcast_id.pkl"),
            person_ids=load_pickle(data_dir / "sorted_pr_dict.pkl"),
        )

    def shortest_path(self, source: str, target: str) -> tuple[str, ...]:
        if source == target:
            return (source,)

        seen = {source}
        queue: deque[tuple[str, tuple[str, ...]]] = deque([(source, (source,))])
        while queue:
            node, path = queue.popleft()
            for neighbor in self._adjacency.get(node, {}):
                if neighbor in seen:
                    continue
                next_path = (*path, neighbor)
                if neighbor == target:
                    return next_path
                seen.add(neighbor)
                queue.append((neighbor, next_path))

        return ()

    def explain(self, source: str, target: str) -> PathResult:
        missing_name = self._first_missing_name(source, target)
        if missing_name is not None:
            suggestion = self.suggest_name(missing_name)
            return PathResult(
                found=False,
                source=source,
                target=target,
                path=(),
                suggestion=suggestion,
                message=(
                    f"Sorry, we could not find {missing_name} in the database."
                    f" Did you mean {suggestion}?"
                ),
            )

        path = self.shortest_path(source, target)
        if not path:
            return PathResult(
                found=False,
                source=source,
                target=target,
                path=(),
                message=f"No connection found between {source} and {target}.",
            )

        return PathResult(
            found=True,
            source=source,
            target=target,
            path=path,
            message=self._path_sentence(path),
        )

    def suggest_name(self, target: str) -> str:
        candidates = [name for name in self.names if name[:1].lower() == target[:1].lower()]
        if not candidates:
            candidates = list(self.names)
        return min(candidates, key=lambda name: ngram_distance(target.lower(), name.lower()))

    def edge_kind(self, left: str, right: str) -> str:
        return self._adjacency[left][right]

    def _first_missing_name(self, source: str, target: str) -> str | None:
        if source not in self.names:
            return source
        if target not in self.names:
            return target
        return None

    def _path_sentence(self, path: tuple[str, ...]) -> str:
        if len(path) == 1:
            return f"{path[0]} is the same person."

        parts = [path[0]]
        for index, node in enumerate(path[1:], start=1):
            previous = path[index - 1]
            kind = self.edge_kind(previous, node)
            if index == 1:
                parts.append(" is a host of " if kind == "host" else " was a guest on ")
            elif index % 2 == 0:
                parts.append(", which is hosted by " if kind == "host" else ", who had as a guest ")
            else:
                parts.append(", who was a guest on ")
            parts.append(node)
        parts.append(".")
        return "".join(parts)


def load_edges(path: Path) -> list[Edge]:
    edges: list[Edge] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            fields = line.rstrip("\n").split("\t", maxsplit=2)
            if len(fields) != 3:
                # Some legacy node names contain embedded newlines, which corrupted a few
                # edgelist rows. Keep loading the usable graph and let data cleanup handle
                # those source records later.
                continue
            left, right, raw_attrs = fields
            attrs = ast.literal_eval(raw_attrs)
            edges.append(Edge(left=left, right=right, kind=attrs.get("attr", "guest")))
    return edges


def load_names(path: Path) -> set[str]:
    with path.open(encoding="utf-8") as handle:
        reader = csv.reader(handle, delimiter="\t")
        return {row[0] for row in reader if row}


def load_pickle(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        value = pickle.load(handle)
    if not isinstance(value, dict):
        raise TypeError(f"Expected {path} to contain a dict, got {type(value).__name__}")
    return value


def ngram_distance(left: str, right: str, n: int = 3) -> float:
    left_grams = ngrams(left, n)
    right_grams = ngrams(right, n)
    if not left_grams and not right_grams:
        return 0.0
    union = left_grams | right_grams
    if not union:
        return 1.0
    return 1 - (len(left_grams & right_grams) / len(union))


def ngrams(value: str, n: int) -> set[str]:
    if len(value) < n:
        return {value}
    return {value[index : index + n] for index in range(len(value) - n + 1)}
