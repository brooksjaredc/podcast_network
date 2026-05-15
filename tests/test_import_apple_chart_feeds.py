from __future__ import annotations

import json
from pathlib import Path

from django.test import TestCase

from podcast_network.ingest.models import ParsedEpisode
from podcast_network.web.catalog.management.commands.import_apple_chart_feeds import (
    AppleChartPodcast,
    collect_genre_ids,
    contains_cjk,
    episode_has_guest_signal,
    import_podcast,
    parse_chart_feed_podcast_ids,
    read_csv,
    write_csv,
)
from podcast_network.web.catalog.models import Feed, Podcast


class ImportAppleChartFeedsTests(TestCase):
    def test_parse_chart_feed_podcast_ids_preserves_order_and_deduplicates(self) -> None:
        payload = {
            "feed": {
                "entry": [
                    {"id": {"attributes": {"im:id": "111"}}},
                    {"id": {"attributes": {"im:id": "222"}}},
                    {"id": {"attributes": {"im:id": "111"}}},
                    {"id": {"attributes": {}}},
                ]
            }
        }

        assert parse_chart_feed_podcast_ids(json.dumps(payload)) == ["111", "222"]

    def test_collect_genre_ids_includes_nested_subgenres(self) -> None:
        genres = {
            "1301": {"subgenres": {"1482": {"subgenres": {}}}},
            "1303": {"subgenres": {}},
        }

        assert collect_genre_ids(genres) == [1301, 1482, 1303]

    def test_import_podcast_creates_feed_and_stores_apple_metadata(self) -> None:
        podcast = AppleChartPodcast(
            apple_id="12345",
            name="Example Chart Show",
            artist_name="Example Network",
            feed_url="https://example.com/rss.xml",
            apple_url="https://podcasts.apple.com/us/podcast/example/id12345",
            chart_sources="genre:26,genre:1303",
        )

        result = import_podcast(podcast)

        assert result.podcasts_created == 1
        assert result.feeds_created == 1
        db_podcast = Podcast.objects.get(name="Example Chart Show")
        assert db_podcast.external_id == "12345"
        assert db_podcast.metadata["apple_podcasts"]["artist_name"] == "Example Network"
        assert db_podcast.metadata["apple_podcasts"]["chart_sources"] == [
            "genre:26",
            "genre:1303",
        ]
        assert Feed.objects.get(podcast=db_podcast).url == "https://example.com/rss.xml"

    def test_import_podcast_skips_cjk_named_podcasts(self) -> None:
        podcast = AppleChartPodcast(
            apple_id="12345",
            name="下一本讀什麼？",
            artist_name="Example Network",
            feed_url="https://example.com/rss.xml",
            apple_url="https://podcasts.apple.com/us/podcast/example/id12345",
            chart_sources="genre:26",
        )

        result = import_podcast(podcast)

        assert result.podcasts_created == 0
        assert Podcast.objects.count() == 0
        assert Feed.objects.count() == 0
        assert contains_cjk("下一本讀什麼？") is True
        assert contains_cjk("Example Chart Show") is False

    def test_episode_guest_signal_detects_common_interview_wording(self) -> None:
        assert episode_has_guest_signal(
            ParsedEpisode(
                guid="1",
                title="Episode 100 with Jane Smith",
                description="",
            )
        )
        assert episode_has_guest_signal(
            ParsedEpisode(
                guid="2",
                title="A solo update",
                description="Today I am joined by Jane Smith to talk about policy.",
            )
        )
        assert not episode_has_guest_signal(
            ParsedEpisode(
                guid="3",
                title="A solo update",
                description="Today I talk about the news and answer listener questions.",
            )
        )

    def test_chart_csv_round_trips_for_screened_imports(self) -> None:
        path = Path("data/test_apple_chart_feeds.csv")
        podcast = AppleChartPodcast(
            apple_id="12345",
            name="Example Chart Show",
            artist_name="Example Network",
            feed_url="https://example.com/rss.xml",
            apple_url="https://podcasts.apple.com/us/podcast/example/id12345",
            chart_sources="genre:26",
        )

        write_csv([podcast], path)

        assert read_csv(path) == [podcast]
