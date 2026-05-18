from __future__ import annotations

import ast
import csv
import pickle
import re
import unicodedata
from collections import deque
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from podcast_network.paths import LEGACY_ANALYSIS_DIR


@dataclass(frozen=True)
class Edge:
    left: str
    right: str
    kind: str
    date: str | None = None
    dates: tuple[str, ...] = ()
    active_start: str | None = None
    active_end: str | None = None

    @property
    def event_dates(self) -> tuple[str, ...]:
        return tuple(sorted({date for date in (*self.dates, self.date or "") if date}))


@dataclass(frozen=True)
class PathMessagePart:
    text: str
    kind: str = "connector"


@dataclass(frozen=True)
class PathResult:
    found: bool
    source: str
    target: str
    path: tuple[str, ...]
    message: str
    message_parts: tuple[PathMessagePart, ...] = ()
    suggestion: str | None = None
    suggested_source: str | None = None
    suggested_target: str | None = None

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
        self._canonical_names = canonical_name_index(names)
        self._adjacency: dict[str, dict[str, Edge]] = {}
        for edge in merge_edges(edges):
            self._adjacency.setdefault(edge.left, {})[edge.right] = edge
            self._adjacency.setdefault(edge.right, {})[edge.left] = edge

    @classmethod
    def from_legacy_dir(cls, data_dir: Path = LEGACY_ANALYSIS_DIR) -> SixDegreesGraph:
        return cls(
            edges=load_edges(data_dir / "six_degrees.edgelist"),
            names=load_names(data_dir / "correct_spellings.csv"),
            podcast_ids=load_pickle(data_dir / "podcast_id.pkl"),
            person_ids=load_pickle(data_dir / "sorted_pr_dict.pkl"),
        )

    def shortest_path(
        self,
        source: str,
        target: str,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> tuple[str, ...]:
        if source == target:
            return (source,)

        seen = {source}
        queue: deque[tuple[str, tuple[str, ...]]] = deque([(source, (source,))])
        while queue:
            node, path = queue.popleft()
            for neighbor in self._ordered_neighbors(
                node,
                is_source=node == source,
                start_date=start_date,
                end_date=end_date,
            ):
                if neighbor in seen:
                    continue
                next_path = (*path, neighbor)
                if neighbor == target:
                    return next_path
                seen.add(neighbor)
                queue.append((neighbor, next_path))

        return ()

    def explain(
        self,
        source: str,
        target: str,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> PathResult:
        canonical_source = self.resolve_name(source)
        canonical_target = self.resolve_name(target)
        missing_field = self._first_missing_field(canonical_source, canonical_target)
        if missing_field is not None:
            missing_name = source if missing_field == "source" else target
            suggestion = self.suggest_name(missing_name)
            suggested_source = suggestion if missing_field == "source" else source
            suggested_target = suggestion if missing_field == "target" else target
            return PathResult(
                found=False,
                source=source,
                target=target,
                path=(),
                suggestion=suggestion,
                suggested_source=suggested_source,
                suggested_target=suggested_target,
                message_parts=(),
                message=(
                    f"Sorry, we could not find {missing_name} in the database."
                    f" Did you mean {suggestion}?"
                ),
            )

        path = self.shortest_path(
            canonical_source,
            canonical_target,
            start_date=start_date,
            end_date=end_date,
        )
        if not path:
            return PathResult(
                found=False,
                source=canonical_source,
                target=canonical_target,
                path=(),
                message_parts=(),
                message=f"No connection found between {canonical_source} and {canonical_target}.",
            )

        message_parts = self._path_sentence_parts(path)
        return PathResult(
            found=True,
            source=canonical_source,
            target=canonical_target,
            path=path,
            message="".join(part.text for part in message_parts),
            message_parts=message_parts,
        )

    def resolve_name(self, target: str) -> str | None:
        if target in self.names:
            return target
        return self._canonical_names.get(normalize_name(target))

    def suggest_name(self, target: str) -> str:
        resolved = self.resolve_name(target)
        if resolved is not None:
            return resolved
        return max(self.names, key=lambda name: name_match_score(target, name))

    def edge_kind(self, left: str, right: str) -> str:
        return self._adjacency[left][right].kind

    def edge_date(self, left: str, right: str) -> str | None:
        return self.edge_date_for_window(left, right)

    def edge_date_for_window(
        self,
        left: str,
        right: str,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> str | None:
        edge = self._adjacency[left][right]
        if edge.kind != "guest":
            return None
        dates = matching_dates(edge.event_dates, start_date=start_date, end_date=end_date)
        if not dates:
            return None
        return dates[-1]

    def _ordered_neighbors(
        self,
        node: str,
        *,
        is_source: bool,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[str]:
        neighbors = self._adjacency.get(node, {})
        if not neighbors:
            return []
        neighbors = {
            neighbor: edge
            for neighbor, edge in neighbors.items()
            if edge_matches_window(edge, start_date=start_date, end_date=end_date)
        }
        if is_source and node in self.names:
            return sorted(neighbors, key=lambda neighbor: neighbors[neighbor].kind != "host")
        return list(neighbors)

    def _first_missing_field(
        self,
        canonical_source: str | None,
        canonical_target: str | None,
    ) -> str | None:
        if canonical_source is None:
            return "source"
        if canonical_target is None:
            return "target"
        return None

    def _path_sentence(self, path: tuple[str, ...]) -> str:
        return "".join(part.text for part in self._path_sentence_parts(path))

    def _path_sentence_parts(self, path: tuple[str, ...]) -> tuple[PathMessagePart, ...]:
        if len(path) == 1:
            return (
                PathMessagePart(path[0], "person"),
                PathMessagePart(" is the same person."),
            )

        parts = [PathMessagePart(path[0], "person")]
        for index, node in enumerate(path[1:], start=1):
            previous = path[index - 1]
            kind = self.edge_kind(previous, node)
            if index == 1:
                text = " is a host of " if kind == "host" else " was a guest on "
            elif index % 2 == 0:
                text = ", which is hosted by " if kind == "host" else ", who had as a guest "
            else:
                text = ", who was a guest on "
            parts.append(PathMessagePart(text))
            parts.append(PathMessagePart(node, "person" if node in self.names else "podcast"))
        parts.append(PathMessagePart("."))
        return tuple(parts)


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
            edges.append(
                Edge(
                    left=left,
                    right=right,
                    kind=attrs.get("attr", "guest"),
                    date=normalize_edge_date(attrs.get("date")),
                    active_start=normalize_edge_date(attrs.get("date"))
                    if attrs.get("attr") == "host"
                    else None,
                    active_end=normalize_edge_date(attrs.get("date"))
                    if attrs.get("attr") == "host"
                    else None,
                )
            )
    return edges


def merge_edges(edges: list[Edge]) -> list[Edge]:
    merged: dict[tuple[str, str], Edge] = {}
    for edge in edges:
        key = tuple(sorted((edge.left, edge.right)))
        existing = merged.get(key)
        if existing is None:
            merged[key] = edge
            continue
        kind = "host" if "host" in (existing.kind, edge.kind) else edge.kind
        left, right = existing.left, existing.right
        event_dates = tuple(sorted({*existing.event_dates, *edge.event_dates}))
        active_dates = [
            date
            for date in (
                existing.active_start,
                existing.active_end,
                edge.active_start,
                edge.active_end,
                *(event_dates if kind == "host" else ()),
            )
            if date
        ]
        merged[key] = Edge(
            left=left,
            right=right,
            kind=kind,
            dates=event_dates if kind == "guest" else (),
            active_start=min(active_dates) if active_dates else None,
            active_end=max(active_dates) if active_dates else None,
        )
    return list(merged.values())


def edge_matches_window(
    edge: Edge,
    *,
    start_date: str | None,
    end_date: str | None,
) -> bool:
    if not start_date and not end_date:
        return True
    if edge.kind == "host":
        event_dates = edge.event_dates
        active_start = edge.active_start or (event_dates[0] if event_dates else None)
        active_end = edge.active_end or (event_dates[-1] if event_dates else None)
        if not active_start and not active_end:
            return False
        active_start = active_start or active_end
        active_end = active_end or active_start
        return date_ranges_overlap(
            active_start=active_start,
            active_end=active_end,
            window_start=start_date,
            window_end=end_date,
        )
    return bool(matching_dates(edge.event_dates, start_date=start_date, end_date=end_date))


def matching_dates(
    dates: tuple[str, ...],
    *,
    start_date: str | None,
    end_date: str | None,
) -> tuple[str, ...]:
    return tuple(
        date
        for date in dates
        if (start_date is None or date >= start_date) and (end_date is None or date <= end_date)
    )


def date_ranges_overlap(
    *,
    active_start: str | None,
    active_end: str | None,
    window_start: str | None,
    window_end: str | None,
) -> bool:
    if active_start is None or active_end is None:
        return False
    if window_end is not None and active_start > window_end:
        return False
    return not (window_start is not None and active_end < window_start)


def load_names(path: Path) -> set[str]:
    with path.open(encoding="utf-8") as handle:
        reader = csv.reader(handle, delimiter="\t")
        return {row[0] for row in reader if row}


def normalize_edge_date(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:10]


def load_pickle(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        value = pickle.load(handle)
    if not isinstance(value, dict):
        raise TypeError(f"Expected {path} to contain a dict, got {type(value).__name__}")
    return value


def canonical_name_index(names: set[str]) -> dict[str, str]:
    index: dict[str, str] = {}
    for name in sorted(names):
        normalized = normalize_name(name)
        if normalized:
            index.setdefault(normalized, name)
    return index


def normalize_name(value: str) -> str:
    without_accents = "".join(
        char
        for char in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(char)
    )
    lowered = without_accents.casefold().replace("&", " and ")
    words = re.sub(r"[^a-z0-9]+", " ", lowered)
    return " ".join(words.split())


def name_match_score(target: str, candidate: str) -> float:
    normalized_target = normalize_name(target)
    normalized_candidate = normalize_name(candidate)
    if not normalized_target or not normalized_candidate:
        return 0.0

    direct_similarity = SequenceMatcher(None, normalized_target, normalized_candidate).ratio()
    sorted_target = " ".join(sorted(normalized_target.split()))
    sorted_candidate = " ".join(sorted(normalized_candidate.split()))
    token_order_similarity = SequenceMatcher(None, sorted_target, sorted_candidate).ratio()
    return max(direct_similarity, token_order_similarity)


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
