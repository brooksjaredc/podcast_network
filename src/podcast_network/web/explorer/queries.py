from __future__ import annotations

from datetime import timedelta

from django.db import OperationalError
from django.db.models import Count, Max, Q, QuerySet
from django.utils import timezone

from podcast_network.cleaning import is_likely_english_podcast_name
from podcast_network.network_metrics import latest_succeeded_metric_run
from podcast_network.web.catalog.models import (
    Appearance,
    Person,
    PersonEntityLink,
    PersonNetworkMetric,
    Podcast,
)
from podcast_network.web.explorer.constants import RANKING_FIELDS
from podcast_network.web.explorer.graph_service import (
    COHOST_EPISODE_SHARE,
    COHOST_EPISODE_THRESHOLD,
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
        people_by_podcast.setdefault(podcast_id, []).append(Person(id=person_id, name=person_name))
    for podcast_id, person_id, person_name in frequent_guest_cohost_rows(podcast_ids):
        key = (podcast_id, person_id)
        if key in seen:
            continue
        seen.add(key)
        people_by_podcast.setdefault(podcast_id, []).append(Person(id=person_id, name=person_name))
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


def home_network_stats() -> dict[str, int]:
    podcast_ids = [
        podcast_id
        for podcast_id, podcast_name in Podcast.objects.filter(episodes__appearances__isnull=False)
        .values_list("id", "name")
        .distinct()
        if is_likely_english_podcast_name(podcast_name)
    ]
    if not podcast_ids:
        return {
            "podcast_count": 0,
            "person_count": 0,
            "guest_appearance_count": 0,
        }
    appearances = Appearance.objects.filter(episode__podcast_id__in=podcast_ids)
    return {
        "podcast_count": len(podcast_ids),
        "person_count": appearances.values("person_id").distinct().count(),
        "guest_appearance_count": appearances.filter(role=Appearance.Role.GUEST).count(),
    }


def podcast_or_none(podcast_id: int | None) -> Podcast | None:
    if podcast_id is None:
        return None
    return Podcast.objects.filter(id=podcast_id).first()


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
