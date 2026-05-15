from pathlib import Path

from django.test import TestCase

from podcast_network.web.catalog.management.commands.import_apple_chart_feeds import (
    AppleChartPodcast,
)
from podcast_network.web.catalog.management.commands.import_spotify_chart_feeds import (
    SpotifyChartShow,
    existing_feed_match,
    import_spotify_resolved_podcast,
    name_score,
    read_resolved_csv,
    spotify_show_from_row,
    write_resolved_csv,
)
from podcast_network.web.catalog.models import Feed, Podcast


class ImportSpotifyChartFeedsTests(TestCase):
    def test_spotify_show_from_row_parses_chart_payload(self) -> None:
        row = {
            "showUri": "spotify:show:abc123",
            "showName": "Example Show",
            "showPublisher": "Example Network",
            "showDescription": "A useful show.",
            "showImageUrl": "https://example.com/image.jpg",
        }

        show = spotify_show_from_row(row, chart_source="spotify:top-podcasts")

        assert show == SpotifyChartShow(
            spotify_uri="spotify:show:abc123",
            spotify_id="abc123",
            name="Example Show",
            publisher="Example Network",
            description="A useful show.",
            image_url="https://example.com/image.jpg",
            chart_sources="spotify:top-podcasts",
        )

    def test_import_spotify_resolved_podcast_creates_feed_and_metadata(self) -> None:
        podcast = AppleChartPodcast(
            apple_id="12345",
            name="Example Spotify Show",
            artist_name="Example Network",
            feed_url="https://example.com/rss.xml",
            apple_url="https://podcasts.apple.com/us/podcast/example/id12345",
            chart_sources="spotify:top-podcasts,spotify:comedy",
        )

        result = import_spotify_resolved_podcast(podcast)

        assert result.podcasts_created == 1
        assert result.feeds_created == 1
        db_podcast = Podcast.objects.get(name="Example Spotify Show")
        assert db_podcast.metadata["spotify_charts"]["resolved_apple_id"] == "12345"
        assert db_podcast.metadata["spotify_charts"]["chart_sources"] == [
            "spotify:top-podcasts",
            "spotify:comedy",
        ]
        assert Feed.objects.get(podcast=db_podcast).url == "https://example.com/rss.xml"

    def test_existing_feed_match_uses_local_database_before_apple_search(self) -> None:
        podcast = Podcast.objects.create(
            name="The Joe Rogan Experience",
            external_id="12345",
            metadata={
                "apple_podcasts": {
                    "id": "12345",
                    "artist_name": "Joe Rogan",
                    "url": "https://podcasts.apple.com/us/podcast/example/id12345",
                }
            },
        )
        Feed.objects.create(podcast=podcast, url="https://example.com/rss.xml")
        show = SpotifyChartShow(
            spotify_uri="spotify:show:abc123",
            spotify_id="abc123",
            name="Joe Rogan Experience",
            publisher="Joe Rogan",
            description="",
            image_url="",
            chart_sources="spotify:top-podcasts",
        )

        resolved, score = existing_feed_match(show)

        assert resolved is not None
        assert score > 0.85
        assert resolved.feed_url == "https://example.com/rss.xml"
        assert resolved.chart_sources == "spotify:top-podcasts"

    def test_resolved_csv_round_trips_for_imports(self) -> None:
        path = Path("data/test_spotify_chart_feeds.csv")
        podcast = AppleChartPodcast(
            apple_id="12345",
            name="Example Spotify Show",
            artist_name="Example Network",
            feed_url="https://example.com/rss.xml",
            apple_url="https://podcasts.apple.com/us/podcast/example/id12345",
            chart_sources="spotify:top-podcasts",
        )

        write_resolved_csv([podcast], path)

        assert [item.apple for item in read_resolved_csv(path)] == [podcast]
        path.unlink()

    def test_name_score_handles_punctuation_and_case(self) -> None:
        assert name_score("The Joe Rogan Experience", "Joe Rogan Experience") > 0.85
