from __future__ import annotations

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render

from podcast_network.web.explorer.services import legacy_repository, six_degrees_graph


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

    durations = [duration for duration in repo.durations if duration.podcast_id == podcast_id]
    predictions = [
        prediction for prediction in repo.predictions if prediction.podcast_id == podcast_id
    ]
    return render(
        request,
        "explorer/podcast_detail.html",
        {
            "podcast": podcast,
            "durations": sorted(durations, key=lambda duration: duration.count, reverse=True)[:50],
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
