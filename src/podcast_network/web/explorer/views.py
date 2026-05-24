from __future__ import annotations

import mimetypes
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from django.conf import settings
from django.contrib.staticfiles import finders
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_sameorigin

from podcast_network.cloud_artifacts import parse_gcs_uri
from podcast_network.data import Duration, LegacyRepository, Person, Podcast, Prediction
from podcast_network.graph import SixDegreesGraph
from podcast_network.graph.six_degrees import PathMessagePart, PathResult
from podcast_network.web.catalog.models import (
    CanonicalPersonEntity,
    FutureLinkPredictionRun,
    FutureLinkWeeklyAuditRun,
    PersonEntityLink,
)
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
    start_date = parse_date_filter(request.GET.get("start_date"))
    end_date = parse_date_filter(request.GET.get("end_date"))
    result = None
    path_graph = None
    path_message_parts = ()
    if source and target:
        repo = legacy_repository()
        graph = six_degrees_graph()
        result = graph.explain(source, target, start_date=start_date, end_date=end_date)
        path_message_parts = link_path_message_parts(repo, result)
        path_graph = build_path_graph(graph, result, start_date=start_date, end_date=end_date)
    return render(
        request,
        "explorer/path.html",
        {
            "source": source,
            "target": target,
            "start_date": start_date or "",
            "end_date": end_date or "",
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
    pages = advanced_pages_with_asset_urls()
    if page not in pages:
        raise Http404("Advanced page not found")
    return render(
        request,
        "explorer/advanced.html",
        {
            "page": pages[page],
            "pages": pages,
            **(advanced_prediction_context(repo) if page == "predictions" else {}),
        },
    )


def advanced_pages_with_asset_urls() -> dict[str, dict[str, Any]]:
    pages = deepcopy(advanced_pages())
    for item in pages.values():
        for section in item["sections"]:
            if section.get("plot"):
                section["plot_url"] = reverse(
                    "explorer:plot_asset",
                    kwargs={"asset_path": section["plot"].removeprefix("plots/")},
                )
            if section.get("image"):
                section["image_url"] = reverse(
                    "explorer:plot_asset",
                    kwargs={"asset_path": section["image"].removeprefix("plots/")},
                )
    return pages


@xframe_options_sameorigin
def plot_asset(request: HttpRequest, asset_path: str) -> HttpResponse:
    if not is_safe_plot_asset_path(asset_path):
        raise Http404("Plot asset not found")
    gcs_uri = str(getattr(settings, "PLOT_ARTIFACT_GCS_URI", ""))
    if gcs_uri:
        try:
            return gcs_plot_asset_response(asset_path=asset_path, gcs_uri=gcs_uri)
        except Exception:
            if not settings.DEBUG:
                raise Http404("Plot asset not found") from None
    static_path = f"plots/{asset_path}"
    local_path = finders.find(static_path)
    if not local_path:
        raise Http404("Plot asset not found")
    return HttpResponse(
        Path(local_path).read_bytes(),
        content_type=plot_content_type(asset_path),
    )


def gcs_plot_asset_response(*, asset_path: str, gcs_uri: str) -> HttpResponse:
    from google.cloud import storage

    bucket_name, blob_prefix = parse_gcs_uri(gcs_uri)
    blob_name = f"{blob_prefix.rstrip('/')}/{asset_path}"
    blob = storage.Client().bucket(bucket_name).blob(blob_name)
    if not blob.exists():
        raise Http404("Plot asset not found")
    response = HttpResponse(blob.download_as_bytes(), content_type=plot_content_type(asset_path))
    response["Cache-Control"] = "public, max-age=300"
    return response


def is_safe_plot_asset_path(asset_path: str) -> bool:
    path = Path(asset_path)
    return (
        bool(asset_path)
        and not path.is_absolute()
        and ".." not in path.parts
        and path.suffix in {".html", ".svg", ".js"}
    )


def plot_content_type(asset_path: str) -> str:
    return mimetypes.guess_type(asset_path)[0] or "application/octet-stream"


def advanced_prediction_context(repo: LegacyRepository) -> dict[str, object]:
    prediction_run = latest_prediction_run()
    if prediction_run is None:
        return {
            "prediction_run": None,
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
            "score_histogram": [],
            "candidate_score_histogram": [],
            "score_histogram_plot": None,
            "recent_link_rows": [],
            "recent_hit_histogram": [],
        }

    predictions = prediction_run["predictions"]
    enrich_prediction_links(predictions)
    audit_run = latest_weekly_audit_run()
    recent_link_rows = audit_run["rows"] if audit_run else []
    enrich_prediction_links(recent_link_rows)
    candidate_score_histogram = metadata_score_histogram_counts(
        prediction_run["metadata"].get("score_histogram")
    )
    recent_hit_histogram = metadata_score_histogram_counts(
        audit_run["metadata"].get("score_histogram") if audit_run else None
    )
    return {
        "prediction_run": prediction_run,
        "predictions": predictions,
        "true_positives": [],
        "score_histogram": score_histogram_counts(predictions),
        "candidate_score_histogram": candidate_score_histogram,
        "score_histogram_plot": score_histogram_plot(
            candidate_counts=candidate_score_histogram,
            hit_counts=recent_hit_histogram,
        ),
        "recent_link_rows": recent_link_rows,
        "recent_hit_histogram": recent_hit_histogram,
        "audit_run": audit_run,
    }


def latest_prediction_run() -> dict[str, object] | None:
    run = FutureLinkPredictionRun.objects.order_by("-cutoff_at", "-created_at").first()
    if run is None:
        return None
    predictions = [
        prediction_row(row)
        for row in run.predictions.select_related("podcast", "canonical").order_by("rank")[:1000]
    ]
    metadata = {
        **run.metadata,
        "cutoff_at": run.cutoff_at.isoformat(),
        "candidate_count": run.candidate_count,
        "scored_podcast_count": run.scored_podcast_count,
        "rows_written": run.rows_written,
        "max_degree": run.max_degree,
        "score_histogram": run.score_histogram,
    }
    return {
        "run_id": run.run_id,
        "metadata": metadata,
        "cutoff_at": run.cutoff_at,
        "predictions": predictions,
        "prediction_by_pair": {
            (row["podcast_id"], row["canonical_id"]): row for row in predictions
        },
    }


def prediction_row(prediction) -> dict[str, object]:
    row: dict[str, object] = {
        "rank": prediction.rank,
        "score": prediction.score,
        "podcast_id": prediction.podcast_id,
        "podcast_name": prediction.podcast.name,
        "canonical_id": prediction.canonical_id,
        "guest_name": prediction.canonical.display_name,
        "distance": prediction.distance,
    }
    row.update(prediction.features)
    return row


def enrich_prediction_links(predictions: list[dict[str, object]]) -> None:
    canonical_ids = [str(row["canonical_id"]) for row in predictions]
    people = CanonicalPersonEntity.objects.in_bulk(canonical_ids)
    person_ids_by_canonical: dict[str, int] = {}
    link_rows = (
        PersonEntityLink.objects.filter(canonical_id__in=canonical_ids)
        .values_list("canonical_id", "observation__person_id")
        .order_by("canonical_id", "observation__person_id")
        .distinct()
    )
    for canonical_id, person_id in link_rows:
        person_ids_by_canonical.setdefault(canonical_id, person_id)
    for row in predictions:
        canonical_id = str(row["canonical_id"])
        person = people.get(canonical_id)
        if not row.get("guest_name") and person:
            row["guest_name"] = person.display_name
        row["person_id"] = person_ids_by_canonical.get(canonical_id)


def latest_weekly_audit_run() -> dict[str, object] | None:
    run = FutureLinkWeeklyAuditRun.objects.order_by("-week_end", "-created_at").first()
    if run is None:
        return None
    rows = [
        audit_link_row(row)
        for row in run.links.select_related("podcast", "canonical").order_by("rank")[:500]
    ]
    metadata = {
        **run.metadata,
        "week_start": run.week_start.isoformat(),
        "week_end": run.week_end.isoformat(),
        "window_days": run.window_days,
        "published_pair_count": run.published_pair_count,
        "repeat_pair_excluded_count": run.repeat_pair_excluded_count,
        "new_link_count": run.new_link_count,
        "scored_link_count": run.scored_link_count,
        "candidate_eligible_count": run.candidate_eligible_count,
        "max_degree": run.max_degree,
        "score_histogram": run.score_histogram,
    }
    return {
        "run_id": run.run_id,
        "metadata": metadata,
        "week_end": run.week_end,
        "rows": rows,
    }


def audit_link_row(link) -> dict[str, object]:
    row: dict[str, object] = {
        "rank": link.rank,
        "score": link.score,
        "podcast_id": link.podcast_id,
        "podcast_name": link.podcast.name,
        "canonical_id": link.canonical_id,
        "guest_name": link.canonical.display_name,
        "candidate_eligible": link.candidate_eligible,
        "link_published_at": link.link_published_at,
        "first_episode_published_at": link.first_episode_published_at,
        "distance": link.distance,
    }
    row.update(link.features)
    return row


def score_histogram_counts(
    predictions: list[dict[str, object]],
    *,
    bin_count: int = 10,
) -> list[int]:
    counts = [0] * bin_count
    if not predictions:
        return counts
    for prediction in predictions:
        score = max(0.0, min(1.0, float(prediction["score"])))
        index = min(bin_count - 1, int(score * bin_count))
        counts[index] += 1
    return counts


def metadata_score_histogram_counts(raw_bins: object, *, bin_count: int = 10) -> list[int]:
    counts = [0] * bin_count
    if not isinstance(raw_bins, list) or not raw_bins:
        return counts
    for raw_bin in raw_bins:
        if not isinstance(raw_bin, dict):
            continue
        lower = float(raw_bin.get("lower", 0.0))
        count = int(raw_bin.get("count", 0))
        index = min(bin_count - 1, max(0, int(lower * bin_count)))
        counts[index] += count
    return counts


def score_histogram_plot(
    *,
    candidate_counts: list[int],
    hit_counts: list[int],
) -> dict[str, object] | None:
    if not any(candidate_counts) and not any(hit_counts):
        return None
    bin_count = max(len(candidate_counts), len(hit_counts))
    candidate_counts = padded_counts(candidate_counts, bin_count)
    hit_counts = padded_counts(hit_counts, bin_count)
    candidate_percent = percent_values(candidate_counts)
    hit_percent = percent_values(hit_counts)
    bin_width = 1 / bin_count
    centers = [(index + 0.5) * bin_width for index in range(bin_count)]
    candidate_hover = [
        f"Score {index / bin_count:.2f}-{(index + 1) / bin_count:.2f}<br>"
        f"All candidates: {candidate_counts[index]:,}<br>"
        f"Share: {candidate_percent[index]:.4f}%"
        for index in range(bin_count)
    ]
    hit_hover = [
        f"Score {index / bin_count:.2f}-{(index + 1) / bin_count:.2f}<br>"
        f"New weekly links: {hit_counts[index]:,}<br>"
        f"Share: {hit_percent[index]:.4f}%"
        for index in range(bin_count)
    ]
    return {
        "data": [
            {
                "type": "bar",
                "name": "All candidates",
                "x": centers,
                "y": candidate_percent,
                "width": bin_width * 0.92,
                "marker": {"color": "#0f766e"},
                "opacity": 0.58,
                "hovertext": candidate_hover,
                "hoverinfo": "text",
            },
            {
                "type": "bar",
                "name": "New weekly links",
                "x": centers,
                "y": hit_percent,
                "width": bin_width * 0.52,
                "marker": {"color": "#b45309"},
                "opacity": 0.78,
                "hovertext": hit_hover,
                "hoverinfo": "text",
            },
        ],
        "layout": {
            "title": {"text": "Prediction Score Distribution"},
            "barmode": "overlay",
            "xaxis": {"title": {"text": "Prediction score"}, "range": [0, 1]},
            "yaxis": {
                "title": {"text": "Percent of population"},
                "type": "log",
                "rangemode": "tozero",
            },
            "legend": {"orientation": "h", "y": 1.12},
            "margin": {"l": 62, "r": 32, "t": 88, "b": 58},
            "font": {"family": "system-ui, sans-serif", "color": "#1f2937"},
            "plot_bgcolor": "white",
            "paper_bgcolor": "white",
        },
        "config": {"displaylogo": False, "responsive": True},
    }


def padded_counts(counts: list[int], size: int) -> list[int]:
    return counts[:size] + [0] * max(0, size - len(counts))


def percent_values(counts: list[int]) -> list[float]:
    total = sum(counts)
    if not total:
        return [0.0 for _count in counts]
    return [count / total * 100 for count in counts]


def parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value))
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def parse_int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def parse_date_filter(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value[:10]).date().isoformat()
    except ValueError:
        return None


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
