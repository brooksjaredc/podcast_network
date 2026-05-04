from __future__ import annotations

from django.core.management import call_command
from django.test import TestCase

from podcast_network.extraction.fake import FakeGuestExtractor
from podcast_network.extraction.pipeline import extract_guest_batch
from podcast_network.web.catalog.models import (
    Episode,
    EpisodeGuestExtraction,
    Feed,
    GuestCandidate,
    Podcast,
)


class GuestExtractionTests(TestCase):
    def test_fake_extraction_persists_guest_candidates(self) -> None:
        episode = create_episode(title="A Conversation with Jane Doe")

        run = extract_guest_batch(
            [episode],
            extractor=FakeGuestExtractor(),
            model="fake-model",
            provider="fake",
        )

        assert run.episodes_succeeded == 1
        extraction = EpisodeGuestExtraction.objects.get(episode=episode)
        assert extraction.status == EpisodeGuestExtraction.Status.SUCCEEDED
        candidate = GuestCandidate.objects.get(extraction=extraction)
        assert candidate.name == "Jane Doe"
        assert candidate.normalized_name == "jane doe"

    def test_extract_guests_command_runs_with_fake_provider(self) -> None:
        episode = create_episode(title="Episode with John Smith")

        call_command("extract_guests", "--provider", "fake", "--episode-id", str(episode.id))

        assert GuestCandidate.objects.filter(name="John Smith").exists()


def create_episode(*, title: str) -> Episode:
    podcast = Podcast.objects.create(name="Example Podcast")
    Feed.objects.create(podcast=podcast, url="https://example.com/rss")
    return Episode.objects.create(
        podcast=podcast,
        guid=title,
        title=title,
        description="A test episode.",
    )
