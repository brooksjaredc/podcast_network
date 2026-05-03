from __future__ import annotations

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render

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
    return render(request, "explorer/podcasts.html", {"podcasts": ordered})


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
            "durations": sorted(
                durations,
                key=lambda duration: duration.count,
                reverse=True,
            )[:50],
            "predictions": sorted(
                predictions,
                key=lambda prediction: prediction.prob,
                reverse=True,
            )[:25],
        },
    )


def people(request: HttpRequest) -> HttpResponse:
    repo = legacy_repository()
    ordered = sorted(repo.people, key=lambda person: person.pr_rank or 999_999)
    query = request.GET.get("q", "").strip()
    if query:
        lowered = query.lower()
        ordered = [person for person in ordered if lowered in person.name.lower()]
    return render(request, "explorer/people.html", {"people": ordered[:500], "query": query})


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
            "people": ordered[:250],
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
    if source and target:
        result = six_degrees_graph().explain(source, target)
    return render(
        request,
        "explorer/path.html",
        {
            "source": source,
            "target": target,
            "result": result,
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
