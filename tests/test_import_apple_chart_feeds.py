from __future__ import annotations

import json

from django.test import TestCase

from podcast_network.web.catalog.management.commands.import_apple_chart_feeds import (
    AppleChartPodcast,
    collect_genre_ids,
    import_podcast,
    parse_chart_feed_podcast_ids,
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
