from __future__ import annotations

from pathlib import Path

from django.test import TestCase

from podcast_network.web.catalog.management.commands.import_legacy_feeds import import_legacy_feeds
from podcast_network.web.catalog.models import Feed, HostCandidate, Podcast


class ImportLegacyFeedsTests(TestCase):
    def test_import_legacy_feeds_creates_podcasts_and_feeds(self) -> None:
        path = self.tmpdir / "meta_podcast_info.csv"
        path.write_text(
            "\tPodcast Name\tHosts\tfeedURL\timageURL\tcategories\tkeywords\tcleaner\t"
            "description\tactive\n"
            "1\tExample Show\t['Example Host']\thttps://example.com/rss\t"
            "https://example.com/image.jpg\t['Comedy']\tguest,host\tclean_example\t"
            "Example description\tTrue\n",
            encoding="utf-8",
        )

        result = import_legacy_feeds(path)

        assert result.podcasts_created == 1
        assert result.feeds_created == 1
        podcast = Podcast.objects.get(name="Example Show")
        assert podcast.external_id == "0"
        assert podcast.image_url == "https://example.com/image.jpg"
        assert podcast.metadata["legacy"]["hosts"] == ["Example Host"]
        assert podcast.metadata["legacy"]["categories"] == ["Comedy"]
        assert HostCandidate.objects.filter(
            extraction__podcast=podcast,
            extraction__model="legacy-metadata",
            extraction__prompt_version="legacy-host-import-v1",
            name="Example Host",
        ).exists()
        feed = Feed.objects.get(podcast=podcast)
        assert feed.url == "https://example.com/rss"
        assert feed.active is True
        assert feed.parser_hint == "clean_example"

    def test_import_legacy_feeds_is_idempotent(self) -> None:
        path = self.tmpdir / "meta_podcast_info.csv"
        path.write_text(
            "\tPodcast Name\tHosts\tfeedURL\timageURL\tcategories\tkeywords\tcleaner\t"
            "description\tactive\n"
            "1\tExample Show\t['Example Host']\thttps://example.com/rss\t\t[]\t\t"
            "clean_example\tExample description\tFalse\n",
            encoding="utf-8",
        )

        import_legacy_feeds(path)
        result = import_legacy_feeds(path)

        assert result.podcasts_created == 0
        assert result.podcasts_updated == 1
        assert result.feeds_created == 0
        assert result.feeds_updated == 1
        assert Podcast.objects.count() == 1
        assert Feed.objects.count() == 1
        assert Feed.objects.get().active is False

    def setUp(self) -> None:
        self.tmpdir = self.enterContext(PathContext())


class PathContext:
    def __enter__(self) -> Path:
        import tempfile

        self._tempdir = tempfile.TemporaryDirectory()
        return Path(self._tempdir.name)

    def __exit__(self, *exc_info: object) -> None:
        self._tempdir.cleanup()
