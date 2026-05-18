from __future__ import annotations

from pathlib import Path

from django.test import TestCase

from podcast_network.ingest.fetch import FetchResult
from podcast_network.ingest.pipeline import ingest_feed, record_feed_failure
from podcast_network.ingest.storage import LocalRawFeedStorage
from podcast_network.web.catalog.models import (
    Episode,
    Feed,
    Podcast,
    RawFeedSnapshot,
    ScrapeRun,
)

RSS_FIXTURE = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example Podcast</title>
    <link>https://example.com</link>
    <description>Example description</description>
    <item>
      <title>First Episode</title>
      <guid>episode-1</guid>
      <link>https://example.com/episodes/1</link>
      <pubDate>Tue, 02 Jan 2024 03:04:05 GMT</pubDate>
      <description>First description</description>
      <enclosure url="https://cdn.example.com/1.mp3" type="audio/mpeg" />
    </item>
    <item>
      <title>Second Episode</title>
      <guid>episode-2</guid>
      <link>https://example.com/episodes/2</link>
      <pubDate>Wed, 03 Jan 2024 03:04:05 GMT</pubDate>
      <description>Second description</description>
    </item>
  </channel>
</rss>
"""


class IngestPipelineTests(TestCase):
    def test_ingest_feed_archives_raw_feed_and_upserts_episodes(self) -> None:
        feed = create_feed()

        result = ingest_feed(
            feed,
            storage=LocalRawFeedStorage(Path(self.tmpdir)),
            fetcher=fixture_fetcher(RSS_FIXTURE),
        )

        assert result.created_episodes == 2
        assert result.updated_episodes == 0
        assert Episode.objects.filter(podcast=feed.podcast).count() == 2
        assert RawFeedSnapshot.objects.filter(feed=feed).count() == 1

        first = Episode.objects.get(guid="episode-1")
        assert first.title == "First Episode"
        assert first.enclosure_url == "https://cdn.example.com/1.mp3"

        feed.refresh_from_db()
        assert feed.last_status == 200
        assert feed.last_content_hash

    def test_reingesting_same_feed_does_not_duplicate_rows(self) -> None:
        feed = create_feed()
        storage = LocalRawFeedStorage(Path(self.tmpdir))
        fetcher = fixture_fetcher(RSS_FIXTURE)

        ingest_feed(feed, storage=storage, fetcher=fetcher)
        feed.refresh_from_db()
        result = ingest_feed(feed, storage=storage, fetcher=fetcher)

        assert result.created_episodes == 0
        assert result.updated_episodes == 2
        assert Episode.objects.filter(podcast=feed.podcast).count() == 2
        assert RawFeedSnapshot.objects.filter(feed=feed).count() == 1

    def test_unchanged_feed_records_success_without_parsing(self) -> None:
        feed = create_feed()
        feed.etag = "abc"
        feed.save(update_fields=["etag"])

        result = ingest_feed(
            feed,
            storage=LocalRawFeedStorage(Path(self.tmpdir)),
            fetcher=not_modified_fetcher,
        )

        assert result.skipped_unchanged is True
        assert Episode.objects.count() == 0
        assert ScrapeRun.objects.get().status == ScrapeRun.Status.SUCCEEDED

    def test_ingest_feed_bounds_long_episode_fields(self) -> None:
        feed = create_feed()
        long_url = "https://example.com/" + ("a" * 1200)
        rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example Podcast</title>
    <item>
      <title>{"Long Title " * 120}</title>
      <guid>{long_url}</guid>
      <link>{long_url}</link>
      <itunes:duration>{"1" * 120}</itunes:duration>
      <enclosure url="{long_url}" type="audio/mpeg" />
    </item>
  </channel>
</rss>
""".encode()

        ingest_feed(
            feed,
            storage=LocalRawFeedStorage(Path(self.tmpdir)),
            fetcher=fixture_fetcher(rss),
        )

        episode = Episode.objects.get()
        assert len(episode.guid) == 1000
        assert len(episode.title) == 1000
        assert len(episode.episode_url) == 1000
        assert len(episode.enclosure_url) == 1000
        assert len(episode.duration_raw) == 100
        assert "..." in episode.guid

    def test_repeated_permanent_http_failures_deactivate_feed_and_podcast(self) -> None:
        feed = create_feed()
        feed.failure_count = 2
        feed.save(update_fields=["failure_count"])

        record_feed_failure(feed, status_code=404)

        feed.refresh_from_db()
        feed.podcast.refresh_from_db()
        assert feed.active is False
        assert feed.podcast.active is False

    def test_non_http_failures_do_not_deactivate_feed(self) -> None:
        feed = create_feed()
        feed.failure_count = 8
        feed.save(update_fields=["failure_count"])

        record_feed_failure(feed, status_code=None)

        feed.refresh_from_db()
        feed.podcast.refresh_from_db()
        assert feed.active is True
        assert feed.podcast.active is True

    def setUp(self) -> None:
        self.tmpdir = self.enterContext(PathContext())


def create_feed() -> Feed:
    podcast = Podcast.objects.create(name="Example Podcast")
    return Feed.objects.create(podcast=podcast, url="https://example.com/feed.xml")


def fixture_fetcher(content: bytes):
    def fetcher(
        url: str,
        *,
        etag: str = "",
        last_modified: str = "",
        timeout_seconds: int = 20,
        max_bytes: int = 25 * 1024 * 1024,
    ) -> FetchResult:
        return FetchResult(
            url=url,
            status_code=200,
            content=content,
            etag="abc",
            last_modified="Tue, 02 Jan 2024 03:04:05 GMT",
        )

    return fetcher


def not_modified_fetcher(
    url: str,
    *,
    etag: str = "",
    last_modified: str = "",
    timeout_seconds: int = 20,
    max_bytes: int = 25 * 1024 * 1024,
) -> FetchResult:
    return FetchResult(url=url, status_code=304, content=b"")


class PathContext:
    def __enter__(self) -> Path:
        import tempfile

        self._tempdir = tempfile.TemporaryDirectory()
        return Path(self._tempdir.name)

    def __exit__(self, *exc_info: object) -> None:
        self._tempdir.cleanup()
