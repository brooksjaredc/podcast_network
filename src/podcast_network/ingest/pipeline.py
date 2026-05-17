from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from urllib.error import HTTPError, URLError

from django.db import close_old_connections, transaction
from django.utils import timezone

from podcast_network.cleaning import is_english_language_code, is_likely_english_podcast_name
from podcast_network.ingest.fetch import FetchResult, fetch_feed
from podcast_network.ingest.models import ParsedEpisode, ParsedFeed
from podcast_network.ingest.parse import parse_feed
from podcast_network.ingest.storage import LocalRawFeedStorage, NoopRawFeedStorage
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
    storage: LocalRawFeedStorage | NoopRawFeedStorage | None = None,
    fetch_timeout_seconds: int = 20,
    max_feed_bytes: int = 25 * 1024 * 1024,
    max_episodes_per_feed: int | None = None,
    concurrency: int = 1,
    progress_callback: Callable[[int, int, int], None] | None = None,
) -> ScrapeRun:
    storage = storage or LocalRawFeedStorage()
    run = ScrapeRun.objects.create(feeds_requested=len(feeds))
    if concurrency > 1:
        return ingest_feeds_concurrently(
            feed_ids=[feed.id for feed in feeds],
            storage=storage,
            scrape_run=run,
            fetch_timeout_seconds=fetch_timeout_seconds,
            max_feed_bytes=max_feed_bytes,
            max_episodes_per_feed=max_episodes_per_feed,
            concurrency=concurrency,
            progress_callback=progress_callback,
        )

    succeeded = 0
    failed = 0
    for processed, feed in enumerate(feeds, start=1):
        try:
            ingest_feed(
                feed,
                storage=storage,
                scrape_run=run,
                fetch_timeout_seconds=fetch_timeout_seconds,
                max_feed_bytes=max_feed_bytes,
                max_episodes_per_feed=max_episodes_per_feed,
            )
            succeeded += 1
        except Exception as exc:  # pragma: no cover - command-level safety net
            failed += 1
            record_feed_failure(feed, status_code=getattr(exc, "code", None))
            ScrapeError.objects.create(
                scrape_run=run,
                feed=feed,
                stage=classify_error_stage(exc),
                message=str(exc),
            )
        if progress_callback:
            progress_callback(processed, succeeded, failed)

    finish_feed_run(run=run, succeeded=succeeded, failed=failed)
    return run


def ingest_feeds_concurrently(
    *,
    feed_ids: list[int],
    storage: LocalRawFeedStorage | NoopRawFeedStorage,
    scrape_run: ScrapeRun,
    fetch_timeout_seconds: int,
    max_feed_bytes: int,
    max_episodes_per_feed: int | None,
    concurrency: int,
    progress_callback: Callable[[int, int, int], None] | None,
) -> ScrapeRun:
    succeeded = 0
    failed = 0
    processed = 0
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(
                ingest_feed_for_run,
                feed_id=feed_id,
                storage=storage,
                scrape_run_id=scrape_run.id,
                fetch_timeout_seconds=fetch_timeout_seconds,
                max_feed_bytes=max_feed_bytes,
                max_episodes_per_feed=max_episodes_per_feed,
            )
            for feed_id in feed_ids
        ]
        for future in as_completed(futures):
            processed += 1
            if future.result():
                succeeded += 1
            else:
                failed += 1
            if progress_callback:
                progress_callback(processed, succeeded, failed)

    scrape_run.refresh_from_db()
    finish_feed_run(run=scrape_run, succeeded=succeeded, failed=failed)
    return scrape_run


def ingest_feed_for_run(
    *,
    feed_id: int,
    storage: LocalRawFeedStorage | NoopRawFeedStorage,
    scrape_run_id: int,
    fetch_timeout_seconds: int,
    max_feed_bytes: int,
    max_episodes_per_feed: int | None,
) -> bool:
    close_old_connections()
    try:
        feed = Feed.objects.select_related("podcast").get(pk=feed_id)
        scrape_run = ScrapeRun.objects.get(pk=scrape_run_id)
        ingest_feed(
            feed,
            storage=storage,
            scrape_run=scrape_run,
            fetch_timeout_seconds=fetch_timeout_seconds,
            max_feed_bytes=max_feed_bytes,
            max_episodes_per_feed=max_episodes_per_feed,
        )
    except Exception as exc:  # pragma: no cover - command-level safety net
        try:
            feed = Feed.objects.get(pk=feed_id)
            record_feed_failure(feed, status_code=getattr(exc, "code", None))
            ScrapeError.objects.create(
                scrape_run_id=scrape_run_id,
                feed=feed,
                stage=classify_error_stage(exc),
                message=str(exc),
            )
        finally:
            close_old_connections()
        return False
    else:
        close_old_connections()
        return True


def finish_feed_run(*, run: ScrapeRun, succeeded: int, failed: int) -> None:
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


def ingest_feed(
    feed: Feed,
    *,
    storage: LocalRawFeedStorage | NoopRawFeedStorage | None = None,
    scrape_run: ScrapeRun | None = None,
    fetcher=fetch_feed,
    parser=parse_feed,
    fetch_timeout_seconds: int = 20,
    max_feed_bytes: int = 25 * 1024 * 1024,
    max_episodes_per_feed: int | None = None,
) -> FeedIngestResult:
    storage = storage or LocalRawFeedStorage()
    scrape_run = scrape_run or ScrapeRun.objects.create(feeds_requested=1)
    fetched_at = timezone.now()

    result: FetchResult = fetcher(
        feed.url,
        etag=feed.etag,
        last_modified=feed.last_modified,
        timeout_seconds=fetch_timeout_seconds,
        max_bytes=max_feed_bytes,
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
    parsed: ParsedFeed = parser(result.content, max_episodes=max_episodes_per_feed)

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
    metadata = dict(podcast.metadata)
    rss_metadata = dict(metadata.get("rss") or {})
    if parsed.language and rss_metadata.get("language") != parsed.language:
        rss_metadata["language"] = parsed.language
        metadata["rss"] = rss_metadata
        podcast.metadata = metadata
        changed_fields.append("metadata")
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

    if not is_english_language_code(parsed.language) or not is_likely_english_podcast_name(
        podcast.name
    ):
        podcast.active = False
        podcast.save(update_fields=["active", "updated_at"])
        feed.active = False
        feed.save(update_fields=["active", "updated_at"])


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


def record_feed_failure(feed: Feed, *, status_code: int | None = None) -> None:
    feed.failure_count += 1
    feed.last_fetched_at = timezone.now()
    update_fields = ["failure_count", "last_fetched_at", "updated_at"]
    if status_code is not None:
        feed.last_status = status_code
        update_fields.append("last_status")
    feed.save(update_fields=update_fields)


def classify_error_stage(exc: Exception) -> str:
    if isinstance(exc, (HTTPError, URLError, TimeoutError)):
        return ScrapeError.Stage.FETCH
    return ScrapeError.Stage.PERSIST
