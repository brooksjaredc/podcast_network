from __future__ import annotations

import csv
import html
import json
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.core.management.base import BaseCommand, CommandError, CommandParser

from podcast_network.web.catalog.models import Feed, Podcast

APPLE_LOOKUP_URL = "https://itunes.apple.com/lookup"
APPLE_GENRES_URL = "https://itunes.apple.com/WebObjects/MZStoreServices.woa/ws/genres"
USER_AGENT = "podcast-network-ingest/0.1"

# Fallback broad US Apple Podcasts chart categories. The command normally pulls
# the live Apple genre taxonomy, but these keep it usable if that endpoint drifts.
DEFAULT_GENRE_IDS = [
    1301,  # Arts
    1303,  # Comedy
    1304,  # Education
    1305,  # Kids & Family
    1309,  # TV & Film
    1310,  # Music
    1314,  # Religion & Spirituality
    1318,  # Technology
    1321,  # Business
    1324,  # Society & Culture
    1325,  # Government
    1326,  # History
    1483,  # Fiction
    1488,  # True Crime
    1489,  # News
    1502,  # Leisure
    1511,  # Government
    1512,  # Health & Fitness
    1545,  # Sports
]


@dataclass(frozen=True)
class AppleChartPodcast:
    apple_id: str
    name: str
    artist_name: str
    feed_url: str
    apple_url: str
    chart_sources: str


@dataclass(frozen=True)
class ImportAppleChartResult:
    discovered: int = 0
    resolved: int = 0
    podcasts_created: int = 0
    podcasts_updated: int = 0
    feeds_created: int = 0
    feeds_existing: int = 0
    missing_feed_url: int = 0

    def __add__(self, other: ImportAppleChartResult) -> ImportAppleChartResult:
        return ImportAppleChartResult(
            discovered=self.discovered + other.discovered,
            resolved=self.resolved + other.resolved,
            podcasts_created=self.podcasts_created + other.podcasts_created,
            podcasts_updated=self.podcasts_updated + other.podcasts_updated,
            feeds_created=self.feeds_created + other.feeds_created,
            feeds_existing=self.feeds_existing + other.feeds_existing,
            missing_feed_url=self.missing_feed_url + other.missing_feed_url,
        )


class Command(BaseCommand):
    help = "Import podcast RSS feeds from Apple Podcasts chart pages."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--country", default="us", help="Apple Podcasts country code.")
        parser.add_argument("--limit", type=int, default=500, help="Maximum feeds to import.")
        parser.add_argument(
            "--genre-id",
            action="append",
            type=int,
            default=[],
            help="Apple Podcasts genre ID to include. Can be passed more than once.",
        )
        parser.add_argument(
            "--csv",
            dest="csv_path",
            default="data/reports/apple_chart_feeds.csv",
            help="Write resolved chart feeds to this CSV file.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Do not write database rows.")

    def handle(self, *args: object, **options: object) -> None:
        country = str(options["country"]).lower()
        limit = int(options["limit"])
        if limit < 1:
            raise CommandError("--limit must be positive.")

        genre_ids = list(options["genre_id"]) or default_genre_ids(country)
        chart_ids = collect_chart_ids(country=country, genre_ids=genre_ids, limit=limit)
        resolved = resolve_apple_podcasts(chart_ids)
        podcasts = resolved[:limit]
        write_csv(podcasts, Path(str(options["csv_path"])))

        result = ImportAppleChartResult(discovered=len(chart_ids), resolved=len(podcasts))
        if not options["dry_run"]:
            for podcast in podcasts:
                result += import_podcast(podcast)

        self.stdout.write(
            self.style.SUCCESS(
                f"Discovered {result.discovered} chart podcasts, resolved {result.resolved}. "
                f"Created {result.podcasts_created} podcasts and {result.feeds_created} feeds. "
                f"Existing feeds {result.feeds_existing}, "
                f"missing feed URLs {result.missing_feed_url}. "
                f"Wrote {options['csv_path']}."
            )
        )


def collect_chart_ids(*, country: str, genre_ids: list[int], limit: int) -> list[tuple[str, str]]:
    seen: dict[str, list[str]] = {}
    for label, url in chart_feed_urls(country, genre_ids):
        try:
            page = fetch_text(url)
        except (HTTPError, URLError, TimeoutError):
            continue
        for apple_id in parse_chart_feed_podcast_ids(page):
            seen.setdefault(apple_id, []).append(label)
            if len(seen) >= limit:
                return [(apple_id, ",".join(sources)) for apple_id, sources in seen.items()]
        time.sleep(0.2)
    return [(apple_id, ",".join(sources)) for apple_id, sources in seen.items()]


def chart_feed_urls(country: str, genre_ids: list[int]) -> list[tuple[str, str]]:
    urls = [("genre:26", apple_top_podcasts_feed_url(country=country, genre_id=26))]
    urls.extend(
        (f"genre:{genre_id}", apple_top_podcasts_feed_url(country=country, genre_id=genre_id))
        for genre_id in genre_ids
    )
    return urls


def apple_top_podcasts_feed_url(*, country: str, genre_id: int) -> str:
    return f"https://itunes.apple.com/{country}/rss/toppodcasts/limit=200/genre={genre_id}/json"


def parse_chart_feed_podcast_ids(page: str) -> list[str]:
    payload = json.loads(page)
    entries = payload.get("feed", {}).get("entry", [])
    ids = []
    for entry in entries:
        attributes = entry.get("id", {}).get("attributes", {})
        apple_id = str(attributes.get("im:id") or "")
        if apple_id:
            ids.append(apple_id)
    return unique(ids)


def default_genre_ids(country: str) -> list[int]:
    try:
        payload = json.loads(
            fetch_text(APPLE_GENRES_URL + "?" + urlencode({"id": "26", "cc": country}))
        )
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return DEFAULT_GENRE_IDS
    podcast_genre = payload.get("26", {})
    genre_ids = collect_genre_ids(podcast_genre.get("subgenres", {}))
    return genre_ids or DEFAULT_GENRE_IDS


def collect_genre_ids(genres: dict) -> list[int]:
    output = []
    for genre_id, genre in genres.items():
        output.append(int(genre_id))
        output.extend(collect_genre_ids(genre.get("subgenres", {})))
    return unique_ints(output)


def resolve_apple_podcasts(chart_ids: list[tuple[str, str]]) -> list[AppleChartPodcast]:
    chart_sources = dict(chart_ids)
    resolved: list[AppleChartPodcast] = []
    for batch in batched([apple_id for apple_id, _ in chart_ids], 100):
        payload = lookup_apple_ids(batch)
        for item in payload.get("results", []):
            apple_id = str(item.get("collectionId") or item.get("trackId") or "")
            feed_url = str(item.get("feedUrl") or "")
            if not apple_id or not feed_url:
                continue
            resolved.append(
                AppleChartPodcast(
                    apple_id=apple_id,
                    name=html.unescape(
                        str(item.get("collectionName") or item.get("trackName") or "")
                    ),
                    artist_name=html.unescape(str(item.get("artistName") or "")),
                    feed_url=feed_url,
                    apple_url=str(item.get("collectionViewUrl") or item.get("trackViewUrl") or ""),
                    chart_sources=chart_sources.get(apple_id, ""),
                )
            )
        time.sleep(0.2)
    return resolved


def lookup_apple_ids(apple_ids: list[str]) -> dict:
    url = APPLE_LOOKUP_URL + "?" + urlencode(
        {"id": ",".join(apple_ids), "entity": "podcast"}
    )
    return json.loads(fetch_text(url))


def import_podcast(podcast: AppleChartPodcast) -> ImportAppleChartResult:
    db_podcast, podcast_created = Podcast.objects.get_or_create(
        name=podcast.name,
        defaults={
            "external_id": podcast.apple_id,
            "metadata": apple_metadata(podcast),
        },
    )
    podcast_updated = False
    metadata = {**db_podcast.metadata, **apple_metadata(podcast)}
    if db_podcast.external_id != podcast.apple_id or db_podcast.metadata != metadata:
        db_podcast.external_id = podcast.apple_id
        db_podcast.metadata = metadata
        db_podcast.save(update_fields=["external_id", "metadata", "updated_at"])
        podcast_updated = not podcast_created

    feed, feed_created = Feed.objects.get_or_create(
        url=podcast.feed_url,
        defaults={"podcast": db_podcast, "active": True},
    )
    if not feed_created and feed.podcast_id != db_podcast.id:
        feed.podcast = db_podcast
        feed.active = True
        feed.save(update_fields=["podcast", "active", "updated_at"])

    return ImportAppleChartResult(
        podcasts_created=int(podcast_created),
        podcasts_updated=int(podcast_updated),
        feeds_created=int(feed_created),
        feeds_existing=int(not feed_created),
    )


def apple_metadata(podcast: AppleChartPodcast) -> dict:
    return {
        "apple_podcasts": {
            "id": podcast.apple_id,
            "artist_name": podcast.artist_name,
            "url": podcast.apple_url,
            "chart_sources": podcast.chart_sources.split(",") if podcast.chart_sources else [],
        }
    }


def fetch_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=20) as response:  # noqa: S310
        return response.read().decode("utf-8")


def write_csv(podcasts: list[AppleChartPodcast], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(AppleChartPodcast.__annotations__))
        writer.writeheader()
        for podcast in podcasts:
            writer.writerow(podcast.__dict__)


def batched[T](items: list[T], size: int) -> list[list[T]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def unique(values: list[str]) -> list[str]:
    seen = set()
    output = []
    for value in values:
        if value not in seen:
            seen.add(value)
            output.append(value)
    return output


def unique_ints(values: list[int]) -> list[int]:
    seen = set()
    output = []
    for value in values:
        if value not in seen:
            seen.add(value)
            output.append(value)
    return output
