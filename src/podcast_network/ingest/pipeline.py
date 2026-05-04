from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from podcast_network.ingest.fetch import FetchResult, fetch_feed
from podcast_network.ingest.models import ParsedEpisode, ParsedFeed
from podcast_network.ingest.parse import parse_feed
from podcast_network.ingest.storage import LocalRawFeedStorage
from podcast_network.web.catalog.models import (
    Episode,
    Feed,
    RawFeedSnapshot,
    ScrapeError,
    ScrapeRun,
)


@dataclass(frozen=True)
class FeedIngestResult:
    feed_id: int
    status_code: int
    created_episodes: int = 0
    updated_episodes: int = 0
    skipped_unchanged: bool = False


def ingest_feeds(
    feeds: list[Feed],
    *,
    storage: LocalRawFeedStorage | None = None,
) -> ScrapeRun:
    storage = storage or LocalRawFeedStorage()
    run = ScrapeRun.objects.create(feeds_requested=len(feeds))
    succeeded = 0
    failed = 0
    for feed in feeds:
        try:
            ingest_feed(feed, storage=storage, scrape_run=run)
            succeeded += 1
        except Exception as exc:  # pragma: no cover - command-level safety net
            failed += 1
            ScrapeError.objects.create(
                scrape_run=run,
                feed=feed,
                stage=ScrapeError.Stage.PERSIST,
                message=str(exc),
            )

    run.feeds_succeeded = succeeded
    run.feeds_failed = failed
    run.finished_at = timezone.now()
    if failed and succeeded:
        run.status = ScrapeRun.Status.PARTIAL
    elif failed:
        run.status = ScrapeRun.Status.FAILED
    else:
        run.status = ScrapeRun.Status.SUCCEEDED
    run.save(
        update_fields=[
            "feeds_succeeded",
            "feeds_failed",
            "finished_at",
            "status",
        ],
    )
    return run


def ingest_feed(
    feed: Feed,
    *,
    storage: LocalRawFeedStorage | None = None,
    scrape_run: ScrapeRun | None = None,
    fetcher=fetch_feed,
    parser=parse_feed,
) -> FeedIngestResult:
    storage = storage or LocalRawFeedStorage()
    scrape_run = scrape_run or ScrapeRun.objects.create(feeds_requested=1)
    fetched_at = timezone.now()

    result: FetchResult = fetcher(
        feed.url,
        etag=feed.etag,
        last_modified=feed.last_modified,
    )
    feed.last_status = result.status_code
    feed.last_fetched_at = fetched_at

    if not result.changed:
        feed.failure_count = 0
        feed.save(
            update_fields=[
                "last_status",
                "last_fetched_at",
                "failure_count",
                "updated_at",
            ],
        )
        finish_single_feed_run(scrape_run)
        return FeedIngestResult(
            feed_id=feed.id,
            status_code=result.status_code,
            skipped_unchanged=True,
        )

    stored = storage.save_feed_snapshot(
        feed_id=feed.id,
        content=result.content,
        fetched_at=fetched_at,
    )
    parsed: ParsedFeed = parser(result.content)

    with transaction.atomic():
        snapshot, _ = RawFeedSnapshot.objects.get_or_create(
            feed=feed,
            content_hash=stored.content_hash,
            defaults={
                "scrape_run": scrape_run,
                "storage_uri": stored.uri,
                "fetched_at": fetched_at,
                "http_status": result.status_code,
                "etag": result.etag,
                "last_modified": result.last_modified,
                "size_bytes": stored.size_bytes,
            },
        )
        sync_podcast_metadata(feed, parsed)
        created, updated = upsert_episodes(feed, parsed.episodes)
        feed.etag = result.etag
        feed.last_modified = result.last_modified
        feed.last_content_hash = snapshot.content_hash
        feed.failure_count = 0
        feed.save(
            update_fields=[
                "etag",
                "last_modified",
                "last_status",
                "last_fetched_at",
                "last_content_hash",
                "failure_count",
                "updated_at",
            ],
        )

    finish_single_feed_run(scrape_run)
    return FeedIngestResult(
        feed_id=feed.id,
        status_code=result.status_code,
        created_episodes=created,
        updated_episodes=updated,
    )


def sync_podcast_metadata(feed: Feed, parsed: ParsedFeed) -> None:
    podcast = feed.podcast
    changed_fields = []
    for field_name, value in {
        "description": parsed.description,
        "website_url": parsed.website_url,
        "image_url": parsed.image_url,
    }.items():
        if value and getattr(podcast, field_name) != value:
            setattr(podcast, field_name, value)
            changed_fields.append(field_name)
    if parsed.title and podcast.name.startswith("Untitled podcast "):
        podcast.name = parsed.title
        changed_fields.append("name")
    if changed_fields:
        podcast.save(update_fields=[*changed_fields, "updated_at"])


def upsert_episodes(feed: Feed, episodes: list[ParsedEpisode]) -> tuple[int, int]:
    created = 0
    updated = 0
    for parsed in episodes:
        _, was_created = Episode.objects.update_or_create(
            podcast=feed.podcast,
            guid=parsed.guid,
            defaults={
                "title": parsed.title,
                "description": parsed.description,
                "published_at": parsed.published_at,
                "episode_url": parsed.episode_url,
                "enclosure_url": parsed.enclosure_url,
                "duration_raw": parsed.duration_raw,
                "explicit": parsed.explicit,
                "raw_data": parsed.raw_data,
            },
        )
        if was_created:
            created += 1
        else:
            updated += 1
    return created, updated


def finish_single_feed_run(scrape_run: ScrapeRun) -> None:
    if scrape_run.feeds_requested != 1 or scrape_run.finished_at:
        return
    scrape_run.feeds_succeeded = 1
    scrape_run.finished_at = timezone.now()
    scrape_run.status = ScrapeRun.Status.SUCCEEDED
    scrape_run.save(
        update_fields=[
            "feeds_succeeded",
            "finished_at",
            "status",
        ],
    )
