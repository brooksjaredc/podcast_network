from functools import lru_cache

from podcast_network.data import LegacyRepository
from podcast_network.graph import SixDegreesGraph


@lru_cache(maxsize=1)
def legacy_repository() -> LegacyRepository:
    return LegacyRepository()


@lru_cache(maxsize=1)
def six_degrees_graph() -> SixDegreesGraph:
    return SixDegreesGraph.from_legacy_dir()

