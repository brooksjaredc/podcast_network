from __future__ import annotations

from django.core.management.base import BaseCommand, CommandParser

from podcast_network.ingest import ingest_feeds
from podcast_network.ingest.storage import LocalRawFeedStorage, NoopRawFeedStorage
from podcast_network.web.catalog.models import Feed, Podcast


class Command(BaseCommand):
    help = "Fetch RSS feeds, archive raw snapshots, and upsert parsed episodes."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--feed-url",
            action="append",
            default=[],
            help="RSS feed URL to ingest. Can be passed more than once.",
        )
        parser.add_argument(
            "--podcast-name",
            default="",
            help="Podcast name to use when creating a single --feed-url feed.",
        )
        parser.add_argument(
            "--inactive",
            action="store_true",
            help=(
                "Include inactive feeds for active interview/unknown podcasts. "
                "Inactive or non-interview podcasts are still skipped."
            ),
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=10,
            help="Per-feed HTTP timeout in seconds.",
        )
        parser.add_argument(
            "--max-feed-mb",
            type=float,
            default=25.0,
            help="Maximum RSS feed response size in MiB. Use 0 to disable.",
        )
        parser.add_argument(
            "--max-episodes-per-feed",
            type=int,
            default=0,
            help=(
                "Maximum number of RSS entries to ingest from each feed. "
                "Use 0 to disable. Useful for weekly updates where old entries "
                "have already been ingested."
            ),
        )
        parser.add_argument(
            "--concurrency",
            type=int,
            default=1,
            help="Number of feeds to fetch in parallel.",
        )
        parser.add_argument(
            "--progress-every",
            type=int,
            default=50,
            help="Print progress after every N processed feeds. Use 0 to disable.",
        )
        parser.add_argument(
            "--raw-snapshot-storage",
            choices=["local", "none"],
            default="local",
            help="Where to store raw RSS snapshots. Use 'none' for Cloud Run jobs.",
        )

    def handle(self, *args: object, **options: object) -> None:
        feed_urls = list(options["feed_url"])
        include_inactive = bool(options["inactive"])
        if feed_urls:
            feeds = [ensure_feed(url, str(options["podcast_name"])) for url in feed_urls]
        else:
            feeds = list(
                Feed.objects.select_related("podcast")
                .filter(podcast__active=True)
                .exclude(podcast__is_interview_podcast=False)
            )
            if not include_inactive:
                feeds = [feed for feed in feeds if feed.active]

        if not feeds:
            self.stdout.write(self.style.WARNING("No feeds to ingest."))
            return

        concurrency = int(options["concurrency"])
        if concurrency < 1:
            raise ValueError("--concurrency must be positive.")
        progress_every = int(options["progress_every"])
        if progress_every < 0:
            raise ValueError("--progress-every cannot be negative.")
        max_feed_mb = float(options["max_feed_mb"])
        if max_feed_mb < 0:
            raise ValueError("--max-feed-mb cannot be negative.")
        max_feed_bytes = int(max_feed_mb * 1024 * 1024) if max_feed_mb else 0
        max_episodes_per_feed = int(options["max_episodes_per_feed"])
        if max_episodes_per_feed < 0:
            raise ValueError("--max-episodes-per-feed cannot be negative.")
        storage = (
            NoopRawFeedStorage()
            if str(options["raw_snapshot_storage"]) == "none"
            else LocalRawFeedStorage()
        )

        def progress(processed: int, succeeded: int, failed: int) -> None:
            if progress_every and processed % progress_every == 0:
                self.stdout.write(
                    f"Processed {processed}/{len(feeds)} feeds: "
                    f"{succeeded} succeeded, {failed} failed."
                )

        run = ingest_feeds(
            feeds,
            storage=storage,
            fetch_timeout_seconds=int(options["timeout"]),
            max_feed_bytes=max_feed_bytes,
            max_episodes_per_feed=max_episodes_per_feed or None,
            concurrency=concurrency,
            progress_callback=progress if progress_every else None,
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Scrape run "
                f"{run.id} {run.status}: "
                f"{run.feeds_succeeded} succeeded, {run.feeds_failed} failed."
            )
        )


def ensure_feed(url: str, podcast_name: str) -> Feed:
    podcast_name = podcast_name or f"Untitled podcast {url}"
    podcast, _ = Podcast.objects.get_or_create(name=podcast_name)
    feed, _ = Feed.objects.get_or_create(url=url, defaults={"podcast": podcast})
    return feed
