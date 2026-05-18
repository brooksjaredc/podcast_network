from __future__ import annotations

from datetime import timedelta

from django.db import OperationalError
from django.db.models import Count, Max, Q, QuerySet
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from podcast_network.cleaning import is_likely_english_podcast_name
from podcast_network.graph import SixDegreesGraph
from podcast_network.graph.six_degrees import PathMessagePart
from podcast_network.network_metrics import latest_succeeded_metric_run
from podcast_network.web.catalog.models import (
    Appearance,
    Person,
    PersonEntityLink,
    PersonNetworkMetric,
    Podcast,
)
from podcast_network.web.explorer.services import (
    COHOST_EPISODE_SHARE,
    COHOST_EPISODE_THRESHOLD,
    database_six_degrees_graph,
)

RANKING_FIELDS = {
    "pr": ("pagerank_rank", "PageRank Rankings"),
    "hub": ("hub_rank", "Hub Rankings"),
    "auth": ("authority_rank", "Authority Rankings"),
    "degree": ("degree_rank", "Degree Centrality Rankings"),
    "bt": ("betweenness_rank", "Betweenness Centrality Rankings"),
    "close": ("closeness_rank", "Closeness Centrality Rankings"),
    "appearances": ("appearances_count", "Guest Appearance Rankings"),
}

RECOMMENDATION_SORTS = {
    "rate": "Highest guest overlap",
    "overlap": "Most shared guests",
}

RANKING_DEFINITIONS = [
    {
        "name": "Guest appearances",
        "description": "Counts how many times a person appears as a guest.",
    },
    {
        "name": "PageRank",
        "description": "Highlights people connected to other important people in the network.",
    },
    {
        "name": "Hub",
        "description": "Highlights guests who point toward many prominent hosts.",
    },
    {
        "name": "Authority",
        "description": "Highlights hosts who receive links from prominent guests.",
    },
    {
        "name": "Degree",
        "description": "Counts how directly connected a person is to the rest of the network.",
    },
    {
        "name": "Betweenness",
        "description": (
            "Highlights people who sit on paths between otherwise separate parts "
            "of the network."
        ),
    },
    {
        "name": "Closeness",
        "description": (
            "Highlights people who are, on average, a short network distance "
            "from everyone else."
        ),
    },
]


def home(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "explorer/home.html",
        {
            "podcast_count": Podcast.objects.count(),
            "person_count": Person.objects.count(),
            "duration_count": Appearance.objects.filter(role=Appearance.Role.GUEST).count(),
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
        Podcast.objects.filter(id__in=excluded_ids)
        .exclude(id__in=selected_ids)
        .order_by("name")
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
        },
    )


def person_network_metric(person: Person) -> PersonNetworkMetric | None:
    try:
        run = latest_succeeded_metric_run()
    except OperationalError:
        return None
    if run is None:
        return None

    canonical_id = (
        PersonEntityLink.objects.filter(observation__person=person)
        .values_list("canonical_id", flat=True)
        .first()
    )
    if canonical_id:
        return (
            PersonNetworkMetric.objects.filter(run=run, canonical_id=canonical_id)
            .select_related("canonical", "representative_person")
            .first()
        )

    return (
        PersonNetworkMetric.objects.filter(run=run, representative_person=person)
        .select_related("canonical", "representative_person")
        .first()
    )


def person_network_rank_rows(metric: PersonNetworkMetric | None) -> list[dict[str, object]]:
    if metric is None:
        return []
    return [
        {
            "label": "PageRank",
            "rank_key": "pr",
            "rank": metric.pagerank_rank,
            "score": metric.pagerank,
        },
        {
            "label": "Hub",
            "rank_key": "hub",
            "rank": metric.hub_rank,
            "score": metric.hub,
        },
        {
            "label": "Authority",
            "rank_key": "auth",
            "rank": metric.authority_rank,
            "score": metric.authority,
        },
        {
            "label": "Degree centrality",
            "rank_key": "degree",
            "rank": metric.degree_rank,
            "score": metric.degree_centrality,
        },
        {
            "label": "Betweenness centrality",
            "rank_key": "bt",
            "rank": metric.betweenness_rank,
            "score": metric.betweenness,
        },
        {
            "label": "Closeness centrality",
            "rank_key": "close",
            "rank": metric.closeness_rank,
            "score": metric.closeness,
        },
    ]


def person_podcast_rows(*, person: Person, role: str):
    return (
        Podcast.objects.filter(episodes__appearances__person=person)
        .annotate(
            appearances_count=Count(
                "episodes__appearances",
                filter=Q(
                    episodes__appearances__person=person,
                    episodes__appearances__role=role,
                ),
            ),
            latest=Max(
                "episodes__published_at",
                filter=Q(
                    episodes__appearances__person=person,
                    episodes__appearances__role=role,
                ),
            ),
        )
        .filter(appearances_count__gt=0)
        .order_by("-appearances_count", "name")
    )


def podcast_recommendations_context(
    *,
    selected_ids: list[int],
    excluded_ids: list[int],
    selected_genres: list[str],
    active_only: bool,
    sort: str,
) -> dict[str, object]:
    if not selected_ids:
        return {"rows": [], "genre_options": []}

    selected_guest_ids = list(
        Appearance.objects.filter(
            role=Appearance.Role.GUEST,
            episode__podcast_id__in=selected_ids,
        )
        .values_list("person_id", flat=True)
        .distinct()
    )
    if not selected_guest_ids:
        return {"rows": [], "genre_options": []}

    score_rows = list(
        Appearance.objects.filter(
            role=Appearance.Role.GUEST,
            person_id__in=selected_guest_ids,
        )
        .exclude(episode__podcast_id__in=selected_ids + excluded_ids)
        .values("episode__podcast_id")
        .annotate(
            shared_guest_count=Count("person_id", distinct=True),
            matching_appearances=Count("id"),
        )
        .filter(shared_guest_count__gt=0)
        .order_by("-shared_guest_count", "-matching_appearances", "episode__podcast__name")[:200]
    )
    candidate_ids = [row["episode__podcast_id"] for row in score_rows]
    score_by_podcast_id = {row["episode__podcast_id"]: row for row in score_rows}
    recommendations_by_id = {
        podcast.id: podcast
        for podcast in Podcast.objects.filter(id__in=candidate_ids).annotate(
            unique_guests=Count(
                "episodes__appearances__person",
                filter=guest_filter("episodes__appearances"),
                distinct=True,
            ),
            latest_episode=Max("episodes__published_at"),
        )
    }
    recommendations = [
        recommendations_by_id[podcast_id]
        for podcast_id in candidate_ids
        if podcast_id in recommendations_by_id
    ]
    for podcast in recommendations:
        scores = score_by_podcast_id[podcast.id]
        podcast.shared_guest_count = scores["shared_guest_count"]
        podcast.matching_appearances = scores["matching_appearances"]
        podcast.recommendation_genres = podcast_genres(podcast)
        podcast.is_active = is_active_podcast(podcast)
        podcast.overlap_rate = recommendation_overlap_rate(podcast)
        podcast.overlap_rate_percent = round(podcast.overlap_rate * 100)
        podcast.exclusion_penalty = 0
    recommendations = english_podcasts(recommendations)
    genre_options = sorted(
        {genre for podcast in recommendations for genre in podcast.recommendation_genres}
    )
    apply_exclusion_penalties(recommendations, excluded_ids=excluded_ids)
    if selected_genres:
        recommendations = [
            podcast
            for podcast in recommendations
            if set(selected_genres) & set(podcast.recommendation_genres)
        ]
    if active_only:
        recommendations = [podcast for podcast in recommendations if podcast.is_active]
    recommendations = sorted(
        recommendations,
        key=lambda podcast: recommendation_sort_key(podcast, sort),
    )
    recommendations = recommendations[:20]
    shared_guests = shared_guests_by_podcast(
        podcast_ids=[podcast.id for podcast in recommendations],
        selected_ids=selected_ids,
        selected_guest_ids=selected_guest_ids,
    )
    explanations = recommendation_explanations(
        selected_ids=selected_ids,
        recommendation_ids=[podcast.id for podcast in recommendations],
    )
    rows = [
        {
            "podcast": podcast,
            "shared_guests": shared_guests.get(podcast.id, []),
            "explanation": explanations.get(podcast.id),
        }
        for podcast in recommendations
    ]
    return {"rows": rows, "genre_options": genre_options}


def recommendation_sort_key(podcast: Podcast, sort: str):
    if sort == "rate":
        return (
            -podcast.adjusted_overlap_rate_score,
            -podcast.overlap_rate,
            -podcast.shared_guest_count,
            -podcast.matching_appearances,
            podcast.name,
        )
    return (
        -podcast.adjusted_recommendation_score,
        -podcast.shared_guest_count,
        -podcast.matching_appearances,
        podcast.name,
    )


def apply_exclusion_penalties(podcasts: list[Podcast], *, excluded_ids: list[int]) -> None:
    for podcast in podcasts:
        podcast.adjusted_recommendation_score = recommendation_base_score(podcast)
        podcast.adjusted_overlap_rate_score = recommendation_overlap_rate_score(podcast)
        podcast.exclusion_penalty = 0
        podcast.exclusion_overlap_count = 0
        podcast.exclusion_genre_count = 0
    if not podcasts or not excluded_ids:
        return

    podcast_ids = [podcast.id for podcast in podcasts]
    excluded_guest_ids = set(
        Appearance.objects.filter(
            role=Appearance.Role.GUEST,
            episode__podcast_id__in=excluded_ids,
        )
        .values_list("person_id", flat=True)
        .distinct()
    )
    candidate_guest_rows = (
        Appearance.objects.filter(
            role=Appearance.Role.GUEST,
            episode__podcast_id__in=podcast_ids,
            person_id__in=excluded_guest_ids,
        )
        .values_list("episode__podcast_id", "person_id")
        .distinct()
    )
    guest_overlap_by_podcast: dict[int, set[int]] = {}
    for podcast_id, person_id in candidate_guest_rows:
        guest_overlap_by_podcast.setdefault(podcast_id, set()).add(person_id)

    excluded_genres = set()
    for podcast in Podcast.objects.filter(id__in=excluded_ids):
        excluded_genres.update(podcast_genres(podcast))

    for podcast in podcasts:
        guest_overlap_count = len(guest_overlap_by_podcast.get(podcast.id, set()))
        genre_overlap_count = len(set(podcast.recommendation_genres) & excluded_genres)
        penalty = guest_overlap_count * 120 + genre_overlap_count * 25
        podcast.exclusion_overlap_count = guest_overlap_count
        podcast.exclusion_genre_count = genre_overlap_count
        podcast.exclusion_penalty = penalty
        podcast.adjusted_recommendation_score = recommendation_base_score(podcast) - penalty
        podcast.adjusted_overlap_rate_score = recommendation_overlap_rate_score(podcast) - penalty


def recommendation_base_score(podcast: Podcast) -> int:
    return podcast.shared_guest_count * 100 + podcast.matching_appearances


def recommendation_overlap_rate(podcast: Podcast) -> float:
    unique_guests = podcast.unique_guests or 0
    if unique_guests == 0:
        return 0
    return podcast.shared_guest_count / unique_guests


def recommendation_overlap_rate_score(podcast: Podcast) -> int:
    return round(recommendation_overlap_rate(podcast) * 10_000) + podcast.shared_guest_count


def recommendation_explanations(
    *,
    selected_ids: list[int],
    recommendation_ids: list[int],
) -> dict[int, dict[str, object]]:
    if not selected_ids or not recommendation_ids:
        return {}

    selected_podcast_names = dict(
        Podcast.objects.filter(id__in=selected_ids).values_list("id", "name")
    )
    selected_guest_rows = (
        Appearance.objects.filter(
            role=Appearance.Role.GUEST,
            episode__podcast_id__in=selected_ids,
        )
        .values_list("episode__podcast_id", "person_id", "person__name")
        .distinct()
    )
    selected_podcasts_by_guest: dict[int, set[int]] = {}
    guest_names: dict[int, str] = {}
    for podcast_id, person_id, person_name in selected_guest_rows:
        selected_podcasts_by_guest.setdefault(person_id, set()).add(podcast_id)
        guest_names[person_id] = person_name

    overlaps: dict[int, dict[int, set[int]]] = {}
    candidate_guest_rows = (
        Appearance.objects.filter(
            role=Appearance.Role.GUEST,
            episode__podcast_id__in=recommendation_ids,
            person_id__in=selected_podcasts_by_guest.keys(),
        )
        .values_list("episode__podcast_id", "person_id")
        .distinct()
    )
    for recommendation_id, person_id in candidate_guest_rows:
        for selected_id in selected_podcasts_by_guest.get(person_id, set()):
            overlaps.setdefault(recommendation_id, {}).setdefault(selected_id, set()).add(
                person_id
            )

    appearance_counts = {
        (row["episode__podcast_id"], row["person_id"]): row["appearances_count"]
        for row in Appearance.objects.filter(
            role=Appearance.Role.GUEST,
            episode__podcast_id__in=selected_ids + recommendation_ids,
            person_id__in=selected_podcasts_by_guest.keys(),
        )
        .values("episode__podcast_id", "person_id")
        .annotate(appearances_count=Count("id"))
    }
    explanations = {}
    for recommendation_id, selected_overlaps in overlaps.items():
        selected_id, guest_ids = max(
            selected_overlaps.items(),
            key=lambda item: (len(item[1]), selected_podcast_names.get(item[0], "")),
        )
        ranked_guest_ids = sorted(
            guest_ids,
            key=lambda guest_id: (
                -(
                    appearance_counts.get((selected_id, guest_id), 0)
                    + appearance_counts.get((recommendation_id, guest_id), 0)
                ),
                -appearance_counts.get((recommendation_id, guest_id), 0),
                guest_names[guest_id],
            ),
        )
        explanations[recommendation_id] = {
            "source_podcast": selected_podcast_names.get(selected_id, ""),
            "guest_count": len(guest_ids),
            "guests": [guest_names[guest_id] for guest_id in ranked_guest_ids[:3]],
        }
    return explanations


def podcast_genres(podcast: Podcast) -> list[str]:
    metadata = podcast.metadata or {}
    genres = []
    legacy = metadata.get("legacy") or {}
    for category in legacy.get("categories") or []:
        category = str(category).strip()
        if category and category not in genres:
            genres.append(category)
    return genres


def is_active_podcast(podcast: Podcast) -> bool:
    if getattr(podcast, "active", True) is False:
        return False
    latest_episode = getattr(podcast, "latest_episode", None)
    if latest_episode is None:
        return True
    return latest_episode >= timezone.now() - timedelta(days=60)


def shared_guests_by_podcast(
    *,
    podcast_ids: list[int],
    selected_ids: list[int],
    selected_guest_ids,
) -> dict[int, list[Person]]:
    if not podcast_ids:
        return {}
    selected_counts = {
        row["person_id"]: row["appearances_count"]
        for row in Appearance.objects.filter(
            role=Appearance.Role.GUEST,
            episode__podcast_id__in=selected_ids,
            person_id__in=selected_guest_ids,
        )
        .values("person_id")
        .annotate(appearances_count=Count("id"))
    }
    rows = (
        Appearance.objects.filter(
            role=Appearance.Role.GUEST,
            episode__podcast_id__in=podcast_ids,
            person_id__in=selected_guest_ids,
        )
        .values("episode__podcast_id", "person_id", "person__name")
        .annotate(appearances_count=Count("id"))
    )
    scored_rows = sorted(
        rows,
        key=lambda row: (
            row["episode__podcast_id"],
            -(selected_counts.get(row["person_id"], 0) + row["appearances_count"]),
            -row["appearances_count"],
            row["person__name"],
        ),
    )
    guests_by_podcast: dict[int, list[Person]] = {}
    for row in scored_rows:
        podcast_id = row["episode__podcast_id"]
        person_id = row["person_id"]
        if len(guests_by_podcast.get(podcast_id, [])) >= 5:
            continue
        person = Person(id=person_id, name=row["person__name"])
        person.shared_appearance_count = selected_counts.get(person_id, 0) + row[
            "appearances_count"
        ]
        guests_by_podcast.setdefault(podcast_id, []).append(person)
    return guests_by_podcast


def common(request: HttpRequest) -> HttpResponse:
    podcasts = english_podcasts(Podcast.objects.order_by("name"))
    first_id = parse_int(request.GET.get("first"))
    second_id = parse_int(request.GET.get("second"))
    first_podcast = podcast_or_none(first_id)
    second_podcast = podcast_or_none(second_id)
    common_people = []
    if first_podcast and second_podcast:
        first_people = Person.objects.filter(
            appearances__role=Appearance.Role.GUEST,
            appearances__episode__podcast=first_podcast,
        )
        common_people = (
            Person.objects.filter(
                id__in=first_people.values("id"),
                appearances__role=Appearance.Role.GUEST,
                appearances__episode__podcast=second_podcast,
            )
            .annotate(
                appearances_count=Count(
                    "appearances",
                    filter=guest_filter("appearances"),
                )
            )
            .order_by("-appearances_count", "name")
            .distinct()[:500]
        )
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
    result = None
    path_graph = None
    path_message_parts = ()
    if source and target:
        from podcast_network.web.explorer.views import build_path_graph

        graph = database_six_degrees_graph()
        result = graph.explain(source, target)
        path_message_parts = link_path_message_parts(graph, result.message_parts)
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


def people_queryset() -> QuerySet[Person]:
    return (
        Person.objects.annotate(
            appearances_count=Count(
                "appearances",
                filter=guest_filter("appearances"),
            ),
            podcast_count=Count(
                "appearances__episode__podcast",
                filter=guest_filter("appearances"),
                distinct=True,
            ),
            latest=Max("appearances__episode__published_at"),
        )
        .filter(appearances_count__gt=0)
        .order_by("-appearances_count", "name")
    )


def metric_people_queryset(*, rank_key: str, query: str) -> QuerySet[PersonNetworkMetric]:
    field_name, _ = RANKING_FIELDS.get(rank_key, RANKING_FIELDS["pr"])
    rows = PersonNetworkMetric.objects.none()
    try:
        run = latest_succeeded_metric_run()
    except OperationalError:
        return rows
    if run is not None:
        rows = (
            PersonNetworkMetric.objects.filter(run=run, representative_person_id__isnull=False)
            .select_related("representative_person")
            .order_by(field_name, "display_name")
        )
        if query:
            rows = rows.filter(display_name__icontains=query)
    return rows


def host_people_by_podcast(podcast_ids: list[int]) -> dict[int, list[Person]]:
    rows = (
        Appearance.objects.filter(
            role=Appearance.Role.HOST,
            episode__podcast_id__in=podcast_ids,
        )
        .select_related("person")
        .order_by("episode__podcast_id", "person__name")
        .values_list("episode__podcast_id", "person_id", "person__name")
        .distinct()
    )
    people_by_podcast: dict[int, list[Person]] = {}
    seen: set[tuple[int, int]] = set()
    for podcast_id, person_id, person_name in rows:
        key = (podcast_id, person_id)
        if key in seen:
            continue
        seen.add(key)
        people_by_podcast.setdefault(podcast_id, []).append(
            Person(id=person_id, name=person_name)
        )
    for podcast_id, person_id, person_name in frequent_guest_cohost_rows(podcast_ids):
        key = (podcast_id, person_id)
        if key in seen:
            continue
        seen.add(key)
        people_by_podcast.setdefault(podcast_id, []).append(
            Person(id=person_id, name=person_name)
        )
    return people_by_podcast


def frequent_guest_cohost_rows(podcast_ids: list[int]):
    if not podcast_ids:
        return []
    episode_counts = dict(
        Podcast.objects.filter(id__in=podcast_ids)
        .annotate(episode_count=Count("episodes", distinct=True))
        .values_list("id", "episode_count")
    )
    rows = (
        Appearance.objects.filter(
            role=Appearance.Role.GUEST,
            episode__podcast_id__in=podcast_ids,
        )
        .values("episode__podcast_id", "person_id", "person__name")
        .annotate(
            guest_episode_count=Count("episode_id", distinct=True),
        )
        .order_by("episode__podcast_id", "person__name")
    )
    return [
        (row["episode__podcast_id"], row["person_id"], row["person__name"])
        for row in rows
        if row["guest_episode_count"] > COHOST_EPISODE_THRESHOLD
        or row["guest_episode_count"]
        > episode_counts.get(row["episode__podcast_id"], 0) * COHOST_EPISODE_SHARE
    ]


def english_podcasts(podcasts) -> list[Podcast]:
    return [podcast for podcast in podcasts if is_likely_english_podcast_name(podcast.name)]


def guest_filter(prefix: str):
    return Q(**{f"{prefix}__role": Appearance.Role.GUEST})


def podcast_or_none(podcast_id: int | None) -> Podcast | None:
    if podcast_id is None:
        return None
    return Podcast.objects.filter(id=podcast_id).first()


def parse_int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def parse_int_list(values: list[str]) -> list[int]:
    parsed = []
    seen = set()
    for value in values:
        try:
            parsed_value = int(value)
        except (TypeError, ValueError):
            continue
        if parsed_value in seen:
            continue
        seen.add(parsed_value)
        parsed.append(parsed_value)
    return parsed


def parse_string_list(values: list[str]) -> list[str]:
    parsed = []
    seen = set()
    for value in values:
        parsed_value = value.strip()
        if not parsed_value or parsed_value in seen:
            continue
        seen.add(parsed_value)
        parsed.append(parsed_value)
    return parsed


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
