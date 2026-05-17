from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

import feedparser
from django.utils import timezone

from podcast_network.ingest.models import ParsedEpisode, ParsedFeed


def parse_feed(content: bytes, *, max_episodes: int | None = None) -> ParsedFeed:
    parsed = feedparser.parse(content)
    feed = parsed.get("feed", {})
    entries = parsed.get("entries", [])
    if max_episodes is not None and max_episodes > 0:
        entries = entries[:max_episodes]
    episodes = [parse_episode(entry) for entry in entries]
    return ParsedFeed(
        title=string_value(feed.get("title")),
        description=string_value(feed.get("description") or feed.get("subtitle")),
        website_url=string_value(feed.get("link")),
        image_url=feed_image_url(feed),
        language=string_value(feed.get("language")),
        episodes=episodes,
    )


def parse_episode(entry: dict[str, Any]) -> ParsedEpisode:
    title = string_value(entry.get("title")) or "Untitled episode"
    guid = episode_guid(entry, title)
    return ParsedEpisode(
        guid=guid,
        title=title,
        description=string_value(entry.get("summary") or entry.get("description")),
        published_at=published_datetime(entry),
        episode_url=string_value(entry.get("link")),
        enclosure_url=enclosure_url(entry),
        duration_raw=string_value(entry.get("itunes_duration")),
        explicit=explicit_value(entry.get("itunes_explicit")),
        raw_data=minimal_raw_entry(entry),
    )


def episode_guid(entry: dict[str, Any], title: str) -> str:
    for key in ("id", "guid", "link"):
        value = string_value(entry.get(key))
        if value:
            return value
    published = string_value(entry.get("published"))
    digest = hashlib.sha256(f"{title}|{published}".encode()).hexdigest()
    return f"generated:{digest}"


def published_datetime(entry: dict[str, Any]) -> datetime | None:
    struct_time = entry.get("published_parsed") or entry.get("updated_parsed")
    if not struct_time:
        return None
    value = datetime(*struct_time[:6])
    return timezone.make_aware(value, timezone=UTC)


def enclosure_url(entry: dict[str, Any]) -> str:
    for enclosure in entry.get("enclosures", []):
        href = string_value(enclosure.get("href"))
        if href:
            return href
    links = entry.get("links", [])
    for link in links:
        if link.get("rel") == "enclosure":
            href = string_value(link.get("href"))
            if href:
                return href
    return ""


def explicit_value(value: Any) -> bool | None:
    normalized = string_value(value).lower()
    if normalized in {"yes", "true", "explicit"}:
        return True
    if normalized in {"no", "false", "clean"}:
        return False
    return None


def feed_image_url(feed: dict[str, Any]) -> str:
    image = feed.get("image")
    if isinstance(image, dict):
        return string_value(image.get("href") or image.get("url"))
    return string_value(feed.get("itunes_image", {}).get("href"))


def minimal_raw_entry(entry: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "id",
        "guid",
        "title",
        "link",
        "published",
        "updated",
        "itunes_duration",
        "itunes_explicit",
    ]
    return {key: entry[key] for key in keys if key in entry}


def string_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()
