from __future__ import annotations

import csv
import json
import re
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.core.management.base import BaseCommand, CommandParser

from podcast_network.ingest.fetch import fetch_feed
from podcast_network.ingest.parse import parse_feed
from podcast_network.web.catalog.models import Feed

APPLE_SEARCH_URL = "https://itunes.apple.com/search"


@dataclass(frozen=True)
class ReplacementCandidate:
    podcast: str
    old_url: str
    candidate_name: str = ""
    candidate_url: str = ""
    apple_url: str = ""
    score: float = 0
    valid: bool = False
    episode_count: int = 0
    newest_episode: str = ""
    error: str = ""


class Command(BaseCommand):
    help = "Search Apple Podcasts for replacement RSS URLs for failed feeds."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--csv",
            dest="csv_path",
            default="data/reports/feed_replacements.csv",
            help="Write candidate replacements to this CSV file.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Limit the number of failed feeds to search.",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=8,
            help="Per-feed validation timeout in seconds.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Update feed URLs for valid high-confidence candidates.",
        )
        parser.add_argument(
            "--min-score",
            type=float,
            default=0.9,
            help="Minimum name-match score required for --apply.",
        )

    def handle(self, *args: object, **options: object) -> None:
        feeds = list(
            Feed.objects.select_related("podcast")
            .filter(active=True, failure_count__gt=0)
            .order_by("podcast__name")
        )
        limit = int(options["limit"])
        if limit:
            feeds = feeds[:limit]

        candidates = [
            discover_replacement(feed, timeout_seconds=int(options["timeout"])) for feed in feeds
        ]
        csv_path = Path(str(options["csv_path"]))
        write_csv(candidates, csv_path)

        applied = 0
        if options["apply"]:
            applied = apply_candidates(candidates, min_score=float(options["min_score"]))

        valid = sum(candidate.valid for candidate in candidates)
        high_confidence = sum(
            candidate.valid and candidate.score >= float(options["min_score"])
            for candidate in candidates
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Searched {len(feeds)} failed feeds. "
                f"Found {valid} valid candidates, {high_confidence} high-confidence. "
                f"Applied {applied}. Wrote {csv_path}."
            )
        )


def discover_replacement(feed: Feed, *, timeout_seconds: int) -> ReplacementCandidate:
    try:
        result = search_apple(feed.podcast.name)
    except Exception as exc:
        return ReplacementCandidate(
            podcast=feed.podcast.name,
            old_url=feed.url,
            error=f"apple search failed: {exc}",
        )

    if result is None:
        return ReplacementCandidate(
            podcast=feed.podcast.name,
            old_url=feed.url,
            error="no apple podcast result",
        )

    candidate_name = str(result.get("collectionName") or "")
    candidate_url = str(result.get("feedUrl") or "")
    apple_url = str(result.get("collectionViewUrl") or "")
    score = name_score(feed.podcast.name, candidate_name)
    if not candidate_url:
        return ReplacementCandidate(
            podcast=feed.podcast.name,
            old_url=feed.url,
            candidate_name=candidate_name,
            apple_url=apple_url,
            score=score,
            error="apple result had no feedUrl",
        )

    try:
        fetched = fetch_feed(candidate_url, timeout_seconds=timeout_seconds)
        parsed = parse_feed(fetched.content)
        newest = max(
            (episode.published_at for episode in parsed.episodes if episode.published_at),
            default=None,
        )
    except Exception as exc:
        return ReplacementCandidate(
            podcast=feed.podcast.name,
            old_url=feed.url,
            candidate_name=candidate_name,
            candidate_url=candidate_url,
            apple_url=apple_url,
            score=score,
            error=f"candidate validation failed: {exc}",
        )

    return ReplacementCandidate(
        podcast=feed.podcast.name,
        old_url=feed.url,
        candidate_name=candidate_name,
        candidate_url=candidate_url,
        apple_url=apple_url,
        score=round(score, 4),
        valid=bool(parsed.episodes),
        episode_count=len(parsed.episodes),
        newest_episode=newest.isoformat() if newest else "",
    )


def search_apple(term: str) -> dict | None:
    url = APPLE_SEARCH_URL + "?" + urlencode(
        {"term": term, "media": "podcast", "entity": "podcast", "limit": 5}
    )
    request = Request(url, headers={"User-Agent": "podcast-network-ingest/0.1"})
    with urlopen(request, timeout=10) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
    results = payload.get("results", [])
    if not results:
        return None
    ranked = sorted(
        results,
        key=lambda result: name_score(term, str(result.get("collectionName") or "")),
        reverse=True,
    )
    time.sleep(0.2)
    return ranked[0]


def apply_candidates(candidates: list[ReplacementCandidate], *, min_score: float) -> int:
    applied = 0
    for candidate in candidates:
        if not candidate.valid or candidate.score < min_score or not candidate.candidate_url:
            continue
        feed = Feed.objects.get(url=candidate.old_url)
        if Feed.objects.filter(url=candidate.candidate_url).exclude(pk=feed.pk).exists():
            continue
        feed.url = candidate.candidate_url
        feed.failure_count = 0
        feed.last_status = None
        feed.etag = ""
        feed.last_modified = ""
        feed.save(
            update_fields=[
                "url",
                "failure_count",
                "last_status",
                "etag",
                "last_modified",
                "updated_at",
            ]
        )
        applied += 1
    return applied


def name_score(first: str, second: str) -> float:
    return SequenceMatcher(None, normalize_name(first), normalize_name(second)).ratio()


def normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def write_csv(candidates: list[ReplacementCandidate], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(ReplacementCandidate.__annotations__))
        writer.writeheader()
        for candidate in candidates:
            writer.writerow(candidate.__dict__)
