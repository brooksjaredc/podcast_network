from __future__ import annotations

from datetime import datetime
from typing import Any

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse

from podcast_network.data import Duration, LegacyRepository, Person, Podcast, Prediction
from podcast_network.graph import SixDegreesGraph
from podcast_network.graph.six_degrees import PathMessagePart, PathResult
from podcast_network.web.explorer.content import advanced_pages
from podcast_network.web.explorer.services import legacy_repository, six_degrees_graph

RANKING_FIELDS = {
    "pr": ("pr_rank", "PageRank Rankings"),
    "hub": ("hub_rank", "Hub Rankings"),
    "auth": ("auth_rank", "Authority Rankings"),
    "degree": ("degree_rank", "Degree Centrality Rankings"),
    "bt": ("bt_rank", "Betweenness Centrality Rankings"),
    "close": ("close_rank", "Closeness Centrality Rankings"),
}


def home(request: HttpRequest) -> HttpResponse:
    repo = legacy_repository()
    return render(
        request,
        "explorer/home.html",
        {
            "podcast_count": len(repo.podcasts),
            "person_count": len(repo.people),
            "duration_count": len(repo.durations),
        },
    )


def podcasts(request: HttpRequest) -> HttpResponse:
    repo = legacy_repository()
    ordered = sorted(repo.podcasts, key=lambda podcast: podcast.degree_rank or 999_999)
    rows = [
        {
            "podcast": podcast,
            "hosts": linked_people(repo, podcast.hosts),
        }
        for podcast in ordered
    ]
    return render(request, "explorer/podcasts.html", {"podcast_rows": rows})


def podcast_detail(request: HttpRequest, podcast_id: int) -> HttpResponse:
    repo = legacy_repository()
    try:
        podcast = repo.podcast(podcast_id)
    except KeyError as exc:
        raise Http404("Podcast not found") from exc

    durations = repo.durations_for_podcast(podcast_id)
    predictions = repo.predictions_for_podcast(podcast_id)
    return render(
        request,
        "explorer/podcast_detail.html",
        {
            "podcast": podcast,
            "durations": duration_rows(
                sorted(
                    durations,
                    key=lambda duration: duration.count,
                    reverse=True,
                )[:50],
            ),
            "predictions": prediction_rows(
                sorted(
                    predictions,
                    key=lambda prediction: prediction.prob,
                    reverse=True,
                )[:25],
            ),
        },
    )


def people(request: HttpRequest) -> HttpResponse:
    repo = legacy_repository()
    ordered = sorted(repo.people, key=lambda person: person.pr_rank or 999_999)
    query = request.GET.get("q", "").strip()
    if query:
        lowered = query.lower()
        ordered = [person for person in ordered if lowered in person.name.lower()]
    return render(
        request,
        "explorer/people.html",
        {"people": person_rows(repo, ordered[:500]), "query": query},
    )


def rankings(request: HttpRequest) -> HttpResponse:
    repo = legacy_repository()
    rank_key = request.GET.get("rank", "pr")
    field_name, label = RANKING_FIELDS.get(rank_key, RANKING_FIELDS["pr"])
    ordered = sorted(repo.people, key=lambda person: getattr(person, field_name) or 999_999)

    query = request.GET.get("q", "").strip()
    suggestion = None
    if query:
        lowered = query.lower()
        matches = [person for person in ordered if lowered in person.name.lower()]
        if matches:
            ordered = matches
        else:
            suggestion = six_degrees_graph().suggest_name(query)

    return render(
        request,
        "explorer/rankings.html",
        {
            "people": person_rows(repo, ordered[:250]),
            "rank": rank_key,
            "rank_label": label,
            "query": query,
            "suggestion": suggestion,
        },
    )


def person_detail(request: HttpRequest, person_id: int) -> HttpResponse:
    repo = legacy_repository()
    try:
        person = repo.person(person_id)
    except KeyError as exc:
        raise Http404("Person not found") from exc

    durations = repo.durations_for_person(person.name)
    predictions = repo.predictions_for_person(person_id)
    return render(
        request,
        "explorer/person_detail.html",
        {
            "person": person,
            "durations": sorted(
                durations,
                key=lambda duration: duration.count,
                reverse=True,
            ),
            "predictions": sorted(
                predictions,
                key=lambda prediction: prediction.prob,
                reverse=True,
            )[:25],
            "host_podcasts": [
                repo.podcasts_by_name[name]
                for name in person.host_podcasts
                if name in repo.podcasts_by_name
            ],
        },
    )


def path(request: HttpRequest) -> HttpResponse:
    source = request.GET.get("source", "").strip()
    target = request.GET.get("target", "").strip()
    result = None
    path_graph = None
    path_message_parts = ()
    if source and target:
        repo = legacy_repository()
        graph = six_degrees_graph()
        result = graph.explain(source, target)
        path_message_parts = link_path_message_parts(repo, result)
        path_graph = build_path_graph(graph, result)
    return render(
        request,
        "explorer/path.html",
        {
            "source": source,
            "target": target,
            "result": result,
            "path_message_parts": path_message_parts,
            "path_graph": path_graph,
        },
    )


def common(request: HttpRequest) -> HttpResponse:
    repo = legacy_repository()
    podcasts = sorted(repo.podcasts, key=lambda podcast: podcast.name)
    first_id = parse_int(request.GET.get("first"))
    second_id = parse_int(request.GET.get("second"))
    pairs = []
    first_podcast = None
    second_podcast = None
    if first_id is not None and second_id is not None:
        first_podcast = repo.podcast(first_id)
        second_podcast = repo.podcast(second_id)
        pairs = repo.common_guests(first_id, second_id)

    return render(
        request,
        "explorer/common.html",
        {
            "podcasts": podcasts,
            "first_id": first_id,
            "second_id": second_id,
            "first_podcast": first_podcast,
            "second_podcast": second_podcast,
            "pairs": pairs,
        },
    )


def advanced(request: HttpRequest, page: str = "overview") -> HttpResponse:
    repo = legacy_repository()
    pages = advanced_pages()
    if page not in pages:
        raise Http404("Advanced page not found")
    return render(
        request,
        "explorer/advanced.html",
        {
            "page": pages[page],
            "pages": pages,
            "predictions": sorted(
                repo.predictions,
                key=lambda prediction: prediction.prob,
                reverse=True,
            ),
            "true_positives": sorted(
                repo.true_positives,
                key=lambda true_positive: true_positive.test_prob,
                reverse=True,
            ),
        },
    )


def parse_int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def link_path_message_parts(
    repo: LegacyRepository,
    result: PathResult,
) -> tuple[dict[str, str], ...]:
    return tuple(link_path_message_part(repo, part) for part in result.message_parts)


def link_path_message_part(repo: LegacyRepository, part: PathMessagePart) -> dict[str, str]:
    linked_part = {
        "text": part.text,
        "kind": part.kind,
        "href": "",
    }
    if part.kind == "person" and part.text in repo.people_by_name:
        linked_part["href"] = reverse(
            "explorer:person_detail",
            args=[repo.people_by_name[part.text].id],
        )
    elif part.kind == "podcast" and part.text in repo.podcasts_by_name:
        linked_part["href"] = reverse(
            "explorer:podcast_detail",
            args=[repo.podcasts_by_name[part.text].id],
        )
    return linked_part


def build_path_graph(graph: SixDegreesGraph, result: PathResult) -> dict[str, Any] | None:
    if not result.found:
        return None

    horizontal_gap = 180
    left_padding = 90
    width = max(720, left_padding * 2 + horizontal_gap * max(len(result.path) - 1, 1))
    nodes = []
    for index, name in enumerate(result.path):
        kind = "person" if name in graph.names else "podcast"
        nodes.append(
            {
                "name": name,
                "kind": kind,
                "x": left_padding + index * horizontal_gap,
                "y": 82 if kind == "person" else 178,
                "label_lines": label_lines(name),
            }
        )

    edges = []
    for index, left in enumerate(result.path[:-1]):
        right = result.path[index + 1]
        left_node = nodes[index]
        right_node = nodes[index + 1]
        role = graph.edge_kind(left, right)
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
                "date": graph.edge_date(left, right) if role == "guest" else None,
                "date_label": edge_date_label(graph.edge_date(left, right))
                if role == "guest"
                else "",
                "label_x": (left_node["x"] + right_node["x"]) / 2,
                "label_y": (left_node["y"] + right_node["y"]) / 2 - 12,
            }
        )

    return {
        "width": width,
        "height": 260,
        "nodes": nodes,
        "edges": edges,
    }


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


def person_rows(repo: LegacyRepository, people: list[Person]) -> list[dict[str, Any]]:
    return [
        {
            "person": person,
            "host_podcast": linked_podcast(repo, person.host_podcast),
            "guest_podcast": linked_podcast(repo, person.guest_podcast),
        }
        for person in people
    ]


def linked_people(repo: LegacyRepository, names: list[str]) -> list[dict[str, Person | str]]:
    return [{"name": name, "person": repo.people_by_name.get(name)} for name in names]


def linked_podcast(repo: LegacyRepository, name: str) -> dict[str, Podcast | str] | None:
    if not name:
        return None
    return {"name": name, "podcast": repo.podcasts_by_name.get(name)}


def duration_rows(durations: list[Duration]) -> list[dict[str, Any]]:
    return [
        {
            "duration": duration,
            "guest": {"name": duration.guests, "person_id": duration.person_id},
        }
        for duration in durations
    ]


def prediction_rows(predictions: list[Prediction]) -> list[dict[str, Any]]:
    return [
        {
            "prediction": prediction,
            "guest": {"name": prediction.guest, "person_id": prediction.person_id},
        }
        for prediction in predictions
    ]
