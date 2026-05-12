from functools import lru_cache

from podcast_network.cleaning import is_likely_english_podcast_name, is_single_token_person_name
from podcast_network.data import LegacyRepository
from podcast_network.graph import SixDegreesGraph
from podcast_network.graph.six_degrees import Edge
from podcast_network.web.catalog.models import Appearance, PersonEntityLink


@lru_cache(maxsize=1)
def legacy_repository() -> LegacyRepository:
    return LegacyRepository()


@lru_cache(maxsize=1)
def six_degrees_graph() -> SixDegreesGraph:
    return SixDegreesGraph.from_legacy_dir()


@lru_cache(maxsize=1)
def database_six_degrees_graph() -> SixDegreesGraph:
    edges: list[Edge] = []
    names: set[str] = set()
    person_ids: dict[str, int] = {}
    podcast_ids: dict[str, int] = {}

    if PersonEntityLink.objects.exists():
        rows = canonical_graph_rows()
    else:
        rows = raw_appearance_graph_rows()
    for person_name, person_id, podcast_name, podcast_id, role in rows:
        if is_single_token_person_name(person_name) or not is_likely_english_podcast_name(
            podcast_name
        ):
            continue
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
        )
        .iterator(chunk_size=10_000)
    )
