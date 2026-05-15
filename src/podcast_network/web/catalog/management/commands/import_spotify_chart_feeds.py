from __future__ import annotations

import csv
import html
import json
import re
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.core.management.base import BaseCommand, CommandError, CommandParser

from podcast_network.web.catalog.management.commands.import_apple_chart_feeds import (
    AppleChartPodcast,
    screen_interview_podcasts,
)
from podcast_network.web.catalog.models import Feed, Podcast

SPOTIFY_CHART_API_URL = "https://podcastcharts.byspotify.com/api/charts/{category}"
APPLE_SEARCH_URL = "https://itunes.apple.com/search"
USER_AGENT = "podcast-network-ingest/0.1"
DEFAULT_SPOTIFY_CATEGORIES = [
    "top-podcasts",
    "trending",
    "arts",
    "business",
    "comedy",
    "education",
    "fiction",
    "health-fitness",
    "history",
    "leisure",
    "music",
    "news",
    "religion-spirituality",
    "science",
    "society-culture",
    "sports",
]


@dataclass(frozen=True)
class SpotifyChartShow:
    spotify_uri: str
    spotify_id: str
    name: str
    publisher: str
    description: str
    image_url: str
    chart_sources: str


@dataclass(frozen=True)
class SpotifyResolvedPodcast:
    spotify: SpotifyChartShow
    apple: AppleChartPodcast | None
    apple_match_score: float = 0.0
    error: str = ""


@dataclass(frozen=True)
class ImportSpotifyChartResult:
    discovered: int = 0
    resolved_to_rss: int = 0
    screened_out: int = 0
    podcasts_created: int = 0
    podcasts_updated: int = 0
    feeds_created: int = 0
    feeds_existing: int = 0

    def __add__(self, other: ImportSpotifyChartResult) -> ImportSpotifyChartResult:
        return ImportSpotifyChartResult(
            discovered=self.discovered + other.discovered,
            resolved_to_rss=self.resolved_to_rss + other.resolved_to_rss,
            screened_out=self.screened_out + other.screened_out,
            podcasts_created=self.podcasts_created + other.podcasts_created,
            podcasts_updated=self.podcasts_updated + other.podcasts_updated,
            feeds_created=self.feeds_created + other.feeds_created,
            feeds_existing=self.feeds_existing + other.feeds_existing,
        )


class Command(BaseCommand):
    help = "Import podcast RSS feeds from Spotify podcast chart pages."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--country", default="us", help="Spotify chart country code.")
        parser.add_argument("--limit", type=int, default=1000, help="Maximum shows to resolve.")
        parser.add_argument(
            "--category",
            action="append",
            default=[],
            help="Spotify chart category slug. Can be passed more than once.",
        )
        parser.add_argument("--min-apple-match-score", type=float, default=0.72)
        parser.add_argument("--screen-interview", action="store_true")
        parser.add_argument("--sample-episodes", type=int, default=50)
        parser.add_argument("--min-guest-episodes", type=int, default=5)
        parser.add_argument("--screen-concurrency", type=int, default=10)
        parser.add_argument(
            "--csv",
            default="data/reports/spotify_chart_feeds.csv",
            help="Write resolved Spotify chart feeds to this CSV file.",
        )
        parser.add_argument(
            "--resolve-report",
            default="data/reports/spotify_chart_resolution.csv",
        )
        parser.add_argument(
            "--screen-report",
            default="data/reports/spotify_chart_interview_screening.csv",
        )
        parser.add_argument(
            "--from-csv",
            default="",
            help="Import podcasts from a previously written Spotify resolved CSV.",
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args: object, **options: object) -> None:
        limit = int(options["limit"])
        if limit < 1:
            raise CommandError("--limit must be positive.")

        from_csv = str(options["from_csv"])
        if from_csv:
            resolved = read_resolved_csv(Path(from_csv))[:limit]
            discovered = 0
        else:
            categories = list(options["category"]) or DEFAULT_SPOTIFY_CATEGORIES
            shows = collect_spotify_chart_shows(
                country=str(options["country"]).lower(),
                categories=categories,
                limit=limit,
            )
            discovered = len(shows)
            resolved = resolve_spotify_shows_to_rss(
                shows,
                min_match_score=float(options["min_apple_match_score"]),
            )
            write_resolution_csv(resolved, Path(str(options["resolve_report"])))

        apple_podcasts = [item.apple for item in resolved if item.apple is not None]
        screened_out = 0
        if options["screen_interview"]:
            screening_results = screen_interview_podcasts(
                apple_podcasts,
                sample_episodes=int(options["sample_episodes"]),
                min_guest_episodes=int(options["min_guest_episodes"]),
                concurrency=int(options["screen_concurrency"]),
            )
            write_screening_csv(screening_results, Path(str(options["screen_report"])))
            apple_podcasts = [result.podcast for result in screening_results if result.qualifies]
            screened_out = len(screening_results) - len(apple_podcasts)

        if not from_csv:
            write_resolved_csv(apple_podcasts, Path(str(options["csv"])))

        result = ImportSpotifyChartResult(
            discovered=discovered,
            resolved_to_rss=len(apple_podcasts),
            screened_out=screened_out,
        )
        if not options["dry_run"]:
            for podcast in apple_podcasts:
                result += import_spotify_resolved_podcast(podcast)

        self.stdout.write(
            self.style.SUCCESS(
                f"Discovered {result.discovered} Spotify chart shows, "
                f"resolved {result.resolved_to_rss} to RSS. "
                f"Screened out {result.screened_out}. "
                f"Created {result.podcasts_created} podcasts and {result.feeds_created} feeds. "
                f"Existing feeds {result.feeds_existing}. "
                f"{'Read ' + from_csv if from_csv else 'Wrote ' + options['csv']}."
            )
        )


def collect_spotify_chart_shows(
    *,
    country: str,
    categories: list[str],
    limit: int,
) -> list[SpotifyChartShow]:
    seen: dict[str, SpotifyChartShow] = {}
    for category in categories:
        category_limit = 200 if category == "top-podcasts" else 50
        rows = fetch_spotify_chart(category=category, country=country, limit=category_limit)
        for row in rows:
            show = spotify_show_from_row(row, chart_source=f"spotify:{category}")
            existing = seen.get(show.spotify_id)
            if existing is None:
                seen[show.spotify_id] = show
            elif show.chart_sources not in existing.chart_sources.split(","):
                seen[show.spotify_id] = SpotifyChartShow(
                    spotify_uri=existing.spotify_uri,
                    spotify_id=existing.spotify_id,
                    name=existing.name,
                    publisher=existing.publisher,
                    description=existing.description,
                    image_url=existing.image_url,
                    chart_sources=f"{existing.chart_sources},{show.chart_sources}",
                )
            if len(seen) >= limit:
                return list(seen.values())
        time.sleep(0.2)
    return list(seen.values())


def fetch_spotify_chart(*, category: str, country: str, limit: int) -> list[dict]:
    url = SPOTIFY_CHART_API_URL.format(category=category) + "?" + urlencode(
        {"region": country, "limit": str(limit)}
    )
    request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    with urlopen(request, timeout=20) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def spotify_show_from_row(row: dict, *, chart_source: str) -> SpotifyChartShow:
    uri = str(row.get("showUri") or "")
    return SpotifyChartShow(
        spotify_uri=uri,
        spotify_id=uri.rsplit(":", maxsplit=1)[-1],
        name=html.unescape(str(row.get("showName") or "")),
        publisher=html.unescape(str(row.get("showPublisher") or "")),
        description=html.unescape(str(row.get("showDescription") or "")),
        image_url=str(row.get("showImageUrl") or ""),
        chart_sources=chart_source,
    )


def resolve_spotify_shows_to_rss(
    shows: list[SpotifyChartShow],
    *,
    min_match_score: float,
) -> list[SpotifyResolvedPodcast]:
    output = []
    for show in shows:
        existing, existing_score = existing_feed_match(show)
        if existing is not None and existing_score >= min_match_score:
            output.append(
                SpotifyResolvedPodcast(
                    spotify=show,
                    apple=existing,
                    apple_match_score=existing_score,
                )
            )
            continue
        try:
            apple, score = search_apple_for_spotify_show(show)
        except Exception as exc:  # noqa: BLE001
            output.append(SpotifyResolvedPodcast(spotify=show, apple=None, error=str(exc)))
            continue
        if apple is None or score < min_match_score:
            output.append(
                SpotifyResolvedPodcast(
                    spotify=show,
                    apple=None,
                    apple_match_score=score,
                    error="no_high_confidence_apple_match",
                )
            )
            continue
        output.append(SpotifyResolvedPodcast(spotify=show, apple=apple, apple_match_score=score))
    return output


def existing_feed_match(show: SpotifyChartShow) -> tuple[AppleChartPodcast | None, float]:
    candidates = (
        Podcast.objects.filter(feeds__isnull=False)
        .only("id", "name", "external_id", "metadata")
        .prefetch_related("feeds")
    )
    best: tuple[Podcast, float] | None = None
    for podcast in candidates.iterator(chunk_size=1000):
        score = name_score(show.name, podcast.name)
        if best is None or score > best[1]:
            best = (podcast, score)
    if best is None:
        return None, 0.0
    podcast, score = best
    feed = podcast.feeds.filter(active=True).first() or podcast.feeds.first()
    if feed is None:
        return None, score
    metadata = podcast.metadata or {}
    apple = metadata.get("apple_podcasts") or {}
    return (
        AppleChartPodcast(
            apple_id=str(podcast.external_id or apple.get("id") or ""),
            name=podcast.name,
            artist_name=str(apple.get("artist_name") or show.publisher),
            feed_url=feed.url,
            apple_url=str(apple.get("url") or ""),
            chart_sources=show.chart_sources,
        ),
        score,
    )


def search_apple_for_spotify_show(
    show: SpotifyChartShow,
) -> tuple[AppleChartPodcast | None, float]:
    payload = apple_search(f"{show.name} {show.publisher}", limit=10)
    best: tuple[dict, float] | None = None
    for item in payload.get("results", []):
        feed_url = str(item.get("feedUrl") or "")
        name = html.unescape(str(item.get("collectionName") or item.get("trackName") or ""))
        if not feed_url or not name:
            continue
        score = max(name_score(show.name, name), name_score(f"{show.name} {show.publisher}", name))
        if best is None or score > best[1]:
            best = (item, score)
    time.sleep(0.2)
    if best is None:
        return None, 0.0
    item, score = best
    return (
        AppleChartPodcast(
            apple_id=str(item.get("collectionId") or item.get("trackId") or ""),
            name=html.unescape(str(item.get("collectionName") or item.get("trackName") or "")),
            artist_name=html.unescape(str(item.get("artistName") or "")),
            feed_url=str(item.get("feedUrl") or ""),
            apple_url=str(item.get("collectionViewUrl") or item.get("trackViewUrl") or ""),
            chart_sources=show.chart_sources,
        ),
        score,
    )


def apple_search(term: str, *, limit: int) -> dict:
    url = APPLE_SEARCH_URL + "?" + urlencode(
        {"term": term, "media": "podcast", "entity": "podcast", "country": "us", "limit": limit}
    )
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=20) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def import_spotify_resolved_podcast(podcast: AppleChartPodcast) -> ImportSpotifyChartResult:
    db_podcast, podcast_created = Podcast.objects.get_or_create(
        name=podcast.name,
        defaults={
            "external_id": podcast.apple_id,
            "metadata": spotify_metadata(podcast),
        },
    )
    metadata = {**db_podcast.metadata}
    spotify = dict(metadata.get("spotify_charts") or {})
    spotify.update(spotify_metadata(podcast)["spotify_charts"])
    metadata["spotify_charts"] = spotify
    podcast_updated = False
    if db_podcast.external_id != podcast.apple_id or db_podcast.metadata != metadata:
        db_podcast.external_id = podcast.apple_id or db_podcast.external_id
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
    return ImportSpotifyChartResult(
        podcasts_created=int(podcast_created),
        podcasts_updated=int(podcast_updated),
        feeds_created=int(feed_created),
        feeds_existing=int(not feed_created),
    )


def spotify_metadata(podcast: AppleChartPodcast) -> dict:
    return {
        "spotify_charts": {
            "resolved_apple_id": podcast.apple_id,
            "resolved_apple_url": podcast.apple_url,
            "chart_sources": podcast.chart_sources.split(",") if podcast.chart_sources else [],
        }
    }


def name_score(first: str, second: str) -> float:
    return SequenceMatcher(None, normalize_name(first), normalize_name(second)).ratio()


def normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def write_resolution_csv(results: list[SpotifyResolvedPodcast], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "spotify_uri",
        "spotify_id",
        "spotify_name",
        "spotify_publisher",
        "chart_sources",
        "apple_id",
        "apple_name",
        "apple_artist_name",
        "feed_url",
        "apple_match_score",
        "error",
    ]
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            apple = result.apple
            writer.writerow(
                {
                    "spotify_uri": result.spotify.spotify_uri,
                    "spotify_id": result.spotify.spotify_id,
                    "spotify_name": result.spotify.name,
                    "spotify_publisher": result.spotify.publisher,
                    "chart_sources": result.spotify.chart_sources,
                    "apple_id": apple.apple_id if apple else "",
                    "apple_name": apple.name if apple else "",
                    "apple_artist_name": apple.artist_name if apple else "",
                    "feed_url": apple.feed_url if apple else "",
                    "apple_match_score": f"{result.apple_match_score:.4f}",
                    "error": result.error,
                }
            )


def write_resolved_csv(podcasts: list[AppleChartPodcast], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(AppleChartPodcast.__annotations__))
        writer.writeheader()
        for podcast in podcasts:
            writer.writerow(podcast.__dict__)


def read_resolved_csv(path: Path) -> list[SpotifyResolvedPodcast]:
    with path.open(newline="", encoding="utf-8") as csv_file:
        output = []
        for row in csv.DictReader(csv_file):
            apple = AppleChartPodcast(
                apple_id=row["apple_id"],
                name=row["name"],
                artist_name=row["artist_name"],
                feed_url=row["feed_url"],
                apple_url=row["apple_url"],
                chart_sources=row["chart_sources"],
            )
            output.append(SpotifyResolvedPodcast(spotify=empty_spotify_show(), apple=apple))
        return output


def empty_spotify_show() -> SpotifyChartShow:
    return SpotifyChartShow("", "", "", "", "", "", "")


def write_screening_csv(results, path: Path) -> None:
    from podcast_network.web.catalog.management.commands.import_apple_chart_feeds import (
        write_screening_csv as write_apple_screening_csv,
    )

    write_apple_screening_csv(results, path)
