from __future__ import annotations

from django.db.models import Count, Max, Q
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render

from podcast_network.web.catalog.models import Appearance, Person, Podcast
from podcast_network.web.explorer.common_guests import common_guest_rows
from podcast_network.web.explorer.constants import (
    RANKING_DEFINITIONS,
    RANKING_FIELDS,
    RECOMMENDATION_SORTS,
)
from podcast_network.web.explorer.graph_service import database_six_degrees_graph
from podcast_network.web.explorer.predictions import (
    future_link_predictions_for_person,
    future_link_predictions_for_podcast,
)
from podcast_network.web.explorer.presentation.path_graph import build_path_graph
from podcast_network.web.explorer.presentation.path_messages import link_path_message_parts
from podcast_network.web.explorer.queries import (
    english_podcasts,
    guest_filter,
    home_network_stats,
    host_people_by_podcast,
    metric_people_queryset,
    people_queryset,
    person_network_metric,
    person_network_rank_rows,
    person_podcast_rows,
    podcast_genres,
    podcast_or_none,
)
from podcast_network.web.explorer.recommendations import podcast_recommendations_context
from podcast_network.web.explorer.utils.request_params import (
    parse_date_filter,
    parse_int,
    parse_int_list,
    parse_string_list,
)


def home(request: HttpRequest) -> HttpResponse:
    stats = home_network_stats()
    return render(
        request,
        "explorer/home.html",
        {
            "podcast_count": stats["podcast_count"],
            "person_count": stats["person_count"],
            "duration_count": stats["guest_appearance_count"],
        },
    )


def podcasts(request: HttpRequest) -> HttpResponse:
    podcasts = list(
        Podcast.objects.annotate(
            guest_appearances=Count(
                "episodes__appearances",
                filter=guest_filter("episodes__appearances"),
            ),
            unique_guests=Count(
                "episodes__appearances__person",
                filter=guest_filter("episodes__appearances"),
                distinct=True,
            ),
            latest_episode=Max("episodes__published_at"),
        )
        .filter(guest_appearances__gt=0)
        .order_by("-guest_appearances", "name")[:1000]
    )
    podcasts = english_podcasts(podcasts)
    hosts_by_podcast = host_people_by_podcast([podcast.id for podcast in podcasts])
    rows = [
        {
            "podcast": podcast,
            "hosts": hosts_by_podcast.get(podcast.id, []),
        }
        for podcast in podcasts
    ]
    return render(request, "explorer/podcasts.html", {"podcast_rows": rows})


def podcast_detail(request: HttpRequest, podcast_id: int) -> HttpResponse:
    try:
        podcast = Podcast.objects.get(id=podcast_id)
    except Podcast.DoesNotExist as exc:
        raise Http404("Podcast not found") from exc

    hosts = host_people_by_podcast([podcast.id]).get(podcast.id, [])
    host_ids = [host.id for host in hosts]
    guest_rows = (
        Person.objects.filter(
            appearances__role=Appearance.Role.GUEST,
            appearances__episode__podcast=podcast,
        )
        .exclude(id__in=host_ids)
        .annotate(
            appearances_count=Count(
                "appearances",
                filter=Q(
                    appearances__role=Appearance.Role.GUEST,
                    appearances__episode__podcast=podcast,
                ),
            ),
            latest=Max(
                "appearances__episode__published_at",
                filter=Q(
                    appearances__role=Appearance.Role.GUEST,
                    appearances__episode__podcast=podcast,
                ),
            ),
        )
        .order_by("-appearances_count", "name")[:100]
    )
    return render(
        request,
        "explorer/podcast_detail.html",
        {
            "podcast": podcast,
            "hosts": hosts,
            "guest_rows": guest_rows,
            "episode_count": podcast.episodes.count(),
            "guest_appearance_count": Appearance.objects.filter(
                role=Appearance.Role.GUEST,
                episode__podcast=podcast,
            ).count(),
            "unique_guest_count": Person.objects.filter(
                appearances__role=Appearance.Role.GUEST,
                appearances__episode__podcast=podcast,
            )
            .exclude(id__in=host_ids)
            .distinct()
            .count(),
            "genres": podcast_genres(podcast),
            "predictions": future_link_predictions_for_podcast(podcast_id=podcast.id),
        },
    )


def people(request: HttpRequest) -> HttpResponse:
    query = request.GET.get("q", "").strip()
    rows = people_queryset()
    if query:
        rows = rows.filter(name__icontains=query)
    return render(
        request,
        "explorer/people.html",
        {"people": rows[:500], "query": query},
    )


def rankings(request: HttpRequest) -> HttpResponse:
    query = request.GET.get("q", "").strip()
    rank_key = request.GET.get("rank", "appearances")
    _, label = RANKING_FIELDS.get(rank_key, RANKING_FIELDS["appearances"])
    if rank_key == "appearances":
        rows = people_queryset()
        if query:
            rows = rows.filter(name__icontains=query)
        rows = rows[:250]
    else:
        rows = metric_people_queryset(rank_key=rank_key, query=query)[:250]
    return render(
        request,
        "explorer/rankings.html",
        {
            "people": rows,
            "rank": rank_key,
            "rank_label": label,
            "ranking_definitions": RANKING_DEFINITIONS,
            "query": query,
            "suggestion": None,
        },
    )


def recommendations(request: HttpRequest) -> HttpResponse:
    selected_ids = parse_int_list(request.GET.getlist("selected"))
    excluded_ids = parse_int_list(request.GET.getlist("excluded"))
    search_query = request.GET.get("q", "").strip()
    selected_genres = parse_string_list(request.GET.getlist("genre"))
    active_only = request.GET.get("active") == "1"
    sort = request.GET.get("sort", "rate")
    if sort not in RECOMMENDATION_SORTS:
        sort = "rate"
    selected_podcasts = list(
        Podcast.objects.filter(id__in=selected_ids)
        .annotate(
            guest_appearances=Count(
                "episodes__appearances",
                filter=guest_filter("episodes__appearances"),
            ),
            unique_guests=Count(
                "episodes__appearances__person",
                filter=guest_filter("episodes__appearances"),
                distinct=True,
            ),
        )
        .order_by("name")
    )
    selected_ids = [podcast.id for podcast in selected_podcasts]
    excluded_podcasts = list(
        Podcast.objects.filter(id__in=excluded_ids).exclude(id__in=selected_ids).order_by("name")
    )
    excluded_ids = [podcast.id for podcast in excluded_podcasts]

    search_results = []
    if search_query:
        search_results = list(
            Podcast.objects.filter(name__icontains=search_query)
            .exclude(id__in=selected_ids + excluded_ids)
            .annotate(
                guest_appearances=Count(
                    "episodes__appearances",
                    filter=guest_filter("episodes__appearances"),
                ),
                unique_guests=Count(
                    "episodes__appearances__person",
                    filter=guest_filter("episodes__appearances"),
                    distinct=True,
                ),
            )
            .filter(guest_appearances__gt=0)
            .order_by("name")[:25]
        )
        search_results = english_podcasts(search_results)

    recommendations_context = podcast_recommendations_context(
        selected_ids=selected_ids,
        excluded_ids=excluded_ids,
        selected_genres=selected_genres,
        active_only=active_only,
        sort=sort,
    )
    return render(
        request,
        "explorer/recommendations.html",
        {
            "selected_ids": selected_ids,
            "selected_podcasts": selected_podcasts,
            "excluded_ids": excluded_ids,
            "excluded_podcasts": excluded_podcasts,
            "search_query": search_query,
            "search_results": search_results,
            "selected_genres": selected_genres,
            "active_only": active_only,
            "sort": sort,
            "sort_options": RECOMMENDATION_SORTS,
            "genre_options": recommendations_context["genre_options"],
            "recommendation_rows": recommendations_context["rows"],
        },
    )


def person_detail(request: HttpRequest, person_id: int) -> HttpResponse:
    try:
        person = Person.objects.get(id=person_id)
    except Person.DoesNotExist as exc:
        raise Http404("Person not found") from exc

    host_podcast_rows = person_podcast_rows(person=person, role=Appearance.Role.HOST)
    podcast_rows = person_podcast_rows(person=person, role=Appearance.Role.GUEST)
    network_metric = person_network_metric(person)
    return render(
        request,
        "explorer/person_detail.html",
        {
            "person": person,
            "host_podcast_rows": host_podcast_rows,
            "podcast_rows": podcast_rows,
            "network_metric": network_metric,
            "network_rank_rows": person_network_rank_rows(network_metric),
            "predictions": future_link_predictions_for_person(person=person),
        },
    )


def common(request: HttpRequest) -> HttpResponse:
    podcasts = english_podcasts(Podcast.objects.order_by("name"))
    first_id = parse_int(request.GET.get("first"))
    second_id = parse_int(request.GET.get("second"))
    first_podcast = podcast_or_none(first_id)
    second_podcast = podcast_or_none(second_id)
    common_people = []
    if first_podcast and second_podcast:
        common_people = common_guest_rows(first_podcast.id, second_podcast.id)
    return render(
        request,
        "explorer/common.html",
        {
            "podcasts": podcasts,
            "first_id": first_id,
            "second_id": second_id,
            "first_podcast": first_podcast,
            "second_podcast": second_podcast,
            "common_people": common_people,
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
        graph = database_six_degrees_graph()
        result = graph.explain(source, target, start_date=start_date, end_date=end_date)
        path_message_parts = link_path_message_parts(graph, result.message_parts)
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
