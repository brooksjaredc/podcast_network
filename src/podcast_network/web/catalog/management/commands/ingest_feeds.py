from __future__ import annotations

from django.core.management.base import BaseCommand, CommandParser

from podcast_network.ingest import ingest_feeds
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
            help="Include inactive feeds stored in the database.",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=20,
            help="Per-feed HTTP timeout in seconds.",
        )

    def handle(self, *args: object, **options: object) -> None:
        feed_urls = list(options["feed_url"])
        include_inactive = bool(options["inactive"])
        if feed_urls:
            feeds = [ensure_feed(url, str(options["podcast_name"])) for url in feed_urls]
        else:
            feeds = list(Feed.objects.select_related("podcast").all())
            if not include_inactive:
                feeds = [feed for feed in feeds if feed.active]

        if not feeds:
            self.stdout.write(self.style.WARNING("No feeds to ingest."))
            return

        run = ingest_feeds(feeds, fetch_timeout_seconds=int(options["timeout"]))
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
