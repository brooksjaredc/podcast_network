from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class ParsedEpisode:
    guid: str
    title: str
    description: str = ""
    published_at: datetime | None = None
    episode_url: str = ""
    enclosure_url: str = ""
    duration_raw: str = ""
    explicit: bool | None = None
    raw_data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedFeed:
    title: str = ""
    description: str = ""
    website_url: str = ""
    image_url: str = ""
    language: str = ""
    episodes: list[ParsedEpisode] = field(default_factory=list)
