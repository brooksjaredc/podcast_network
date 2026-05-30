import logging
from pathlib import Path
from tempfile import gettempdir
from threading import Lock
from time import monotonic

from django.conf import settings
from django.db.models import Count

from podcast_network.cleaning import is_likely_english_podcast_name
from podcast_network.cloud_artifacts import download_gcs_to_path
from podcast_network.graph import SixDegreesGraph
from podcast_network.graph.six_degrees import Edge
from podcast_network.web.catalog.models import Appearance, PersonEntityLink, Podcast
from podcast_network.web.explorer.graph_artifact import load_graph_artifact

COHOST_EPISODE_THRESHOLD = 100
COHOST_EPISODE_SHARE = 0.20

logger = logging.getLogger(__name__)

_DATABASE_GRAPH_CACHE: tuple[float, SixDegreesGraph] | None = None
_DATABASE_GRAPH_CACHE_LOCK = Lock()


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

    with _DATABASE_GRAPH_CACHE_LOCK:
        now = monotonic()
        if (
            _DATABASE_GRAPH_CACHE is not None
            and ttl_seconds > 0
            and now - _DATABASE_GRAPH_CACHE[0] < ttl_seconds
        ):
            return _DATABASE_GRAPH_CACHE[1]

        started = monotonic()
        graph = configured_six_degrees_graph_artifact() or build_database_six_degrees_graph()
        elapsed = monotonic() - started
        _DATABASE_GRAPH_CACHE = (monotonic(), graph)
        logger.info(
            "Loaded database six-degrees graph in %.2fs with %d people and %d podcasts.",
            elapsed,
            graph.person_count,
            graph.podcast_count,
        )
        return graph


def clear_database_six_degrees_graph_cache() -> None:
    global _DATABASE_GRAPH_CACHE
    _DATABASE_GRAPH_CACHE = None


database_six_degrees_graph.cache_clear = clear_database_six_degrees_graph_cache


def configured_six_degrees_graph_artifact() -> SixDegreesGraph | None:
    artifact_path = configured_graph_artifact_path()
    gcs_uri = str(getattr(settings, "SIX_DEGREES_GRAPH_ARTIFACT_GCS_URI", "")).strip()
    if gcs_uri:
        try:
            download_gcs_to_path(gcs_uri=gcs_uri, local_path=artifact_path)
        except Exception:
            logger.warning("Could not download six-degrees graph artifact from %s.", gcs_uri)
            return None
    elif not artifact_path.exists():
        return None

    try:
        artifact = load_graph_artifact(artifact_path)
    except Exception:
        logger.warning("Could not load six-degrees graph artifact from %s.", artifact_path)
        return None

    logger.info(
        "Loaded six-degrees graph artifact from %s created at %s.",
        artifact_path,
        artifact.metadata.get("created_at", "unknown"),
    )
    return artifact.graph


def configured_graph_artifact_path() -> Path:
    artifact_path = str(getattr(settings, "SIX_DEGREES_GRAPH_ARTIFACT_PATH", "")).strip()
    if artifact_path:
        return Path(artifact_path)
    return Path(gettempdir()) / "podcast_network" / "six_degrees_graph.pkl.gz"


def build_database_six_degrees_graph() -> SixDegreesGraph:
    edges: list[Edge] = []
    names: set[str] = set()
    person_ids: dict[str, int] = {}
    podcast_ids: dict[str, int] = {}

    use_canonical_links = PersonEntityLink.objects.exists()
    cohost_keys = frequent_guest_cohost_keys(use_canonical_links=use_canonical_links)
    rows = canonical_graph_rows() if use_canonical_links else raw_appearance_graph_rows()
    for person_name, person_id, podcast_name, podcast_id, role, entity_id, published_at in rows:
        if not is_likely_english_podcast_name(podcast_name):
            continue
        if (entity_id or person_id, podcast_id) in cohost_keys:
            role = Appearance.Role.HOST
        names.add(person_name)
        person_ids.setdefault(person_name, person_id)
        podcast_ids.setdefault(podcast_name, podcast_id)
        edges.append(
            Edge(
                left=person_name,
                right=podcast_name,
                kind=role,
                date=published_at.date().isoformat() if published_at else None,
            )
        )

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
            "observation__episode__published_at",
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
            "episode__published_at",
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
