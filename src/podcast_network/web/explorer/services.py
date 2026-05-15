from functools import lru_cache
from time import monotonic

from django.conf import settings
from django.db.models import Count

from podcast_network.cleaning import is_likely_english_podcast_name
from podcast_network.data import LegacyRepository
from podcast_network.graph import SixDegreesGraph
from podcast_network.graph.six_degrees import Edge
from podcast_network.web.catalog.models import Appearance, PersonEntityLink, Podcast

COHOST_EPISODE_THRESHOLD = 100
COHOST_EPISODE_SHARE = 0.20

_DATABASE_GRAPH_CACHE: tuple[float, SixDegreesGraph] | None = None


@lru_cache(maxsize=1)
def legacy_repository() -> LegacyRepository:
    return LegacyRepository()


@lru_cache(maxsize=1)
def six_degrees_graph() -> SixDegreesGraph:
    return SixDegreesGraph.from_legacy_dir()


def database_six_degrees_graph() -> SixDegreesGraph:
    global _DATABASE_GRAPH_CACHE
    ttl_seconds = int(getattr(settings, "DATABASE_GRAPH_CACHE_TTL_SECONDS", 300))
    now = monotonic()
    if (
        _DATABASE_GRAPH_CACHE is not None
        and ttl_seconds > 0
        and now - _DATABASE_GRAPH_CACHE[0] < ttl_seconds
    ):
        return _DATABASE_GRAPH_CACHE[1]

    graph = build_database_six_degrees_graph()
    _DATABASE_GRAPH_CACHE = (now, graph)
    return graph


def clear_database_six_degrees_graph_cache() -> None:
    global _DATABASE_GRAPH_CACHE
    _DATABASE_GRAPH_CACHE = None


database_six_degrees_graph.cache_clear = clear_database_six_degrees_graph_cache


def build_database_six_degrees_graph() -> SixDegreesGraph:
    edges: list[Edge] = []
    names: set[str] = set()
    person_ids: dict[str, int] = {}
    podcast_ids: dict[str, int] = {}

    use_canonical_links = PersonEntityLink.objects.exists()
    cohost_keys = frequent_guest_cohost_keys(use_canonical_links=use_canonical_links)
    rows = canonical_graph_rows() if use_canonical_links else raw_appearance_graph_rows()
    for person_name, person_id, podcast_name, podcast_id, role, entity_id in rows:
        if not is_likely_english_podcast_name(podcast_name):
            continue
        if (entity_id or person_id, podcast_id) in cohost_keys:
            role = Appearance.Role.HOST
        names.add(person_name)
        person_ids.setdefault(person_name, person_id)
        podcast_ids.setdefault(podcast_name, podcast_id)
        edges.append(Edge(left=person_name, right=podcast_name, kind=role))

    return SixDegreesGraph(edges=edges, names=names, podcast_ids=podcast_ids, person_ids=person_ids)


def canonical_graph_rows():
    return (
        PersonEntityLink.objects.filter(
            observation__role__in=[Appearance.Role.GUEST, Appearance.Role.HOST],
        )
        .select_related(
            "canonical",
            "observation__person",
            "observation__episode__podcast",
        )
        .values_list(
            "canonical__display_name",
            "observation__person_id",
            "observation__episode__podcast__name",
            "observation__episode__podcast_id",
            "observation__role",
            "canonical_id",
        )
        .iterator(chunk_size=10_000)
    )


def raw_appearance_graph_rows():
    return (
        Appearance.objects.filter(role__in=[Appearance.Role.GUEST, Appearance.Role.HOST])
        .select_related("person", "episode__podcast")
        .values_list(
            "person__name",
            "person_id",
            "episode__podcast__name",
            "episode__podcast_id",
            "role",
            "person_id",
        )
        .iterator(chunk_size=10_000)
    )


def frequent_guest_cohost_keys(*, use_canonical_links: bool) -> set[tuple[str | int, int]]:
    episode_counts = dict(
        Podcast.objects.annotate(episode_count=Count("episodes", distinct=True)).values_list(
            "id",
            "episode_count",
        )
    )
    if use_canonical_links:
        rows = (
            PersonEntityLink.objects.filter(observation__role=Appearance.Role.GUEST)
            .values("canonical_id", "observation__episode__podcast_id")
            .annotate(
                guest_episode_count=Count("observation__episode_id", distinct=True),
            )
        )
        return {
            (row["canonical_id"], row["observation__episode__podcast_id"])
            for row in rows
            if is_cohost_count(
                guest_episode_count=row["guest_episode_count"],
                podcast_episode_count=episode_counts.get(
                    row["observation__episode__podcast_id"],
                    0,
                ),
            )
        }
    else:
        rows = (
            Appearance.objects.filter(role=Appearance.Role.GUEST)
            .values("person_id", "episode__podcast_id")
            .annotate(
                guest_episode_count=Count("episode_id", distinct=True),
            )
        )
        return {
            (row["person_id"], row["episode__podcast_id"])
            for row in rows
            if is_cohost_count(
                guest_episode_count=row["guest_episode_count"],
                podcast_episode_count=episode_counts.get(row["episode__podcast_id"], 0),
            )
        }


def is_cohost_count(*, guest_episode_count: int, podcast_episode_count: int) -> bool:
    return (
        guest_episode_count > COHOST_EPISODE_THRESHOLD
        or guest_episode_count > podcast_episode_count * COHOST_EPISODE_SHARE
    )
