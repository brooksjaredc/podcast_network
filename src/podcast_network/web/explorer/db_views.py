from __future__ import annotations

from django.db.models import Count, ExpressionWrapper, F, FloatField, Max, Q, QuerySet, Value
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse

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
    run = latest_succeeded_metric_run()
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
    run = latest_succeeded_metric_run()
    rows = PersonNetworkMetric.objects.none()
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
    episode_share_cutoff = ExpressionWrapper(
        F("podcast_episode_count") * Value(COHOST_EPISODE_SHARE),
        output_field=FloatField(),
    )
    return (
        Appearance.objects.filter(
            role=Appearance.Role.GUEST,
            episode__podcast_id__in=podcast_ids,
        )
        .values("episode__podcast_id", "person_id", "person__name")
        .annotate(
            guest_episode_count=Count("episode_id", distinct=True),
            podcast_episode_count=Count("episode__podcast__episodes", distinct=True),
        )
        .filter(
            Q(guest_episode_count__gt=COHOST_EPISODE_THRESHOLD)
            | Q(guest_episode_count__gt=episode_share_cutoff)
        )
        .order_by("episode__podcast_id", "person__name")
        .values_list("episode__podcast_id", "person_id", "person__name")
    )


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
