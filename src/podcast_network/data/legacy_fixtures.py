from __future__ import annotations

import ast
import json
import math
from functools import cached_property
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from podcast_network.paths import LEGACY_ANALYSIS_DIR


class Podcast(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    name: str
    podcast_id: int
    hosts_raw: str = Field(alias="hosts")
    categories_raw: str = Field(alias="categories")
    imgurl: str
    description: str = ""
    percent_unique: float = 0
    num_guests: int = 0
    num_unique: int = 0
    avg_day_diff: float = 0
    active: bool = False
    premier: str = ""
    avg_ep_lengths: str = ""
    cat_bias: str = ""
    close_rank: int = 0
    bt_rank: int = 0
    degree_rank: int = 0
    hub_leader_score: float = 0
    bt_diff_leader_score: float = 0

    @field_validator("description", mode="before")
    @classmethod
    def coerce_description(cls, value: Any) -> str:
        return coerce_legacy_string(value)

    @property
    def hosts(self) -> list[str]:
        return list(ast.literal_eval(self.hosts_raw))

    @property
    def categories(self) -> list[str]:
        return list(ast.literal_eval(self.categories_raw))


class Person(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    name: str
    person_id: int = 0
    pr_rank: int = 0
    hub_rank: int = 0
    auth_rank: int = 0
    close_rank: int = 0
    bt_rank: int = 0
    degree_rank: int = 0
    top_category: str = ""
    host_podcast: str = ""
    guest_podcast: str = ""
    host_podcasts_raw: str | list[str] = Field(default="", alias="host_podcasts")
    guest_podcasts_raw: str | list[str] = Field(default="", alias="guest_podcasts")

    @property
    def host_podcasts(self) -> list[str]:
        return parse_legacy_list(self.host_podcasts_raw)

    @property
    def guest_podcasts(self) -> list[str]:
        return parse_legacy_list(self.guest_podcasts_raw)


class Duration(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    podcast: str
    podcast_id: int
    guests: str
    person_id: int
    hours: str = ""
    count: int = 0
    recent: str = ""


class SimilarPodcast(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    podcast1: str
    podcast2: str
    podcast2_id: int
    score: int


class Prediction(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    podcast: str
    podcast_id: int
    guest: str
    person_id: int
    prob: float


class TruePositive(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    podcast: str
    podcast_id: int
    guest: str
    person_id: int
    test_prob: float


class LegacyRepository:
    """Read-only access to copied legacy fixtures.

    This gives the new app a narrow compatibility layer while the old pipeline is replaced.
    """

    def __init__(self, data_dir: Path = LEGACY_ANALYSIS_DIR) -> None:
        self.data_dir = data_dir

    @cached_property
    def podcasts(self) -> list[Podcast]:
        return load_fixture(self.data_dir / "podcast_info.json", Podcast)

    @cached_property
    def people(self) -> list[Person]:
        return load_fixture(self.data_dir / "all_people.json", Person)

    @cached_property
    def durations(self) -> list[Duration]:
        return load_fixture(self.data_dir / "guest_duration_podcast.json", Duration)

    @cached_property
    def similarities(self) -> list[SimilarPodcast]:
        return load_fixture(self.data_dir / "similarities.json", SimilarPodcast)

    @cached_property
    def predictions(self) -> list[Prediction]:
        return load_fixture(self.data_dir / "link_preds_final.json", Prediction)

    @cached_property
    def true_positives(self) -> list[TruePositive]:
        return load_fixture(self.data_dir / "true_positives.json", TruePositive)

    def podcast(self, podcast_id: int) -> Podcast:
        return self._by_id(self.podcasts, podcast_id)

    def person(self, person_id: int) -> Person:
        return self._by_id(self.people, person_id)

    @staticmethod
    def _by_id[FixtureModel: BaseModel](
        items: list[FixtureModel],
        item_id: int,
    ) -> FixtureModel:
        try:
            return next(item for item in items if item.id == item_id)
        except StopIteration as exc:
            raise KeyError(item_id) from exc


def load_fixture[FixtureModel: BaseModel](
    path: Path,
    model: type[FixtureModel],
) -> list[FixtureModel]:
    raw_records = json.loads(path.read_text(encoding="utf-8"))
    return [
        model.model_validate({"id": record["pk"], **record["fields"]})
        for record in raw_records
    ]


def parse_legacy_list(value: str | list[str]) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if not value:
        return []
    parsed: Any = ast.literal_eval(value)
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def coerce_legacy_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value)
