from __future__ import annotations

from django.test import TestCase

from podcast_network.extraction.host_models import (
    ExtractedPodcastHostResult,
    PodcastHostExtractionResult,
)
from podcast_network.extraction.host_prompt import build_podcast_host_prompt
from podcast_network.web.catalog.management.commands.extract_podcast_hosts import (
    host_kind,
    persist_successful_extraction,
    select_podcasts,
)
from podcast_network.web.catalog.models import (
    ExtractionRun,
    HostCandidate,
    Podcast,
    PodcastHostExtraction,
)


class PodcastHostExtractionTests(TestCase):
    def test_prompt_uses_podcast_name_description_and_metadata(self) -> None:
        podcast = Podcast.objects.create(
            name="Two Ts In A Pod with Teddi Mellencamp and Tamra Judge",
            description="A Bravo recap podcast.",
            metadata={"apple_podcasts": {"artist_name": "iHeartPodcasts"}},
        )

        prompt = build_podcast_host_prompt(podcast)

        assert "Podcast title: Two Ts In A Pod" in prompt.input_text
        assert "A Bravo recap podcast." in prompt.input_text
        assert "Apple artist/publisher: iHeartPodcasts" in prompt.input_text
        assert "Extract the regular human hosts" in prompt.instructions

    def test_selector_excludes_successful_existing_extractions(self) -> None:
        podcast = Podcast.objects.create(name="Example Podcast")
        run = ExtractionRun.objects.create(
            model="gpt-5-mini",
            provider="openai",
            prompt_version="podcast-host-extraction-v1",
            episodes_requested=1,
        )
        PodcastHostExtraction.objects.create(
            podcast=podcast,
            extraction_run=run,
            status=PodcastHostExtraction.Status.SUCCEEDED,
            prompt_version="podcast-host-extraction-v1",
            model="gpt-5-mini",
            input_text="",
        )

        selected = select_podcasts(
            podcast_ids=[],
            limit=10,
            model="gpt-5-mini",
            prompt_version="podcast-host-extraction-v1",
            force=False,
        )

        assert selected == []

    def test_persist_success_creates_host_candidates(self) -> None:
        podcast = Podcast.objects.create(name="Example Podcast")
        run = ExtractionRun.objects.create(
            model="gpt-5-mini",
            provider="openai",
            prompt_version="podcast-host-extraction-v1",
            episodes_requested=1,
        )
        result = PodcastHostExtractionResult(
            hosts=[
                ExtractedPodcastHostResult(
                    name="JANE DOE",
                    kind="host",
                    confidence=0.95,
                    evidence="Hosted by Jane Doe",
                ),
                ExtractedPodcastHostResult(
                    name="John Smith",
                    kind="co-host",
                    confidence=0.9,
                    evidence="co-hosted by John Smith",
                ),
            ],
            input_tokens=10,
            output_tokens=5,
        )

        persist_successful_extraction(
            podcast=podcast,
            extraction_run=run,
            model="gpt-5-mini",
            prompt_version="podcast-host-extraction-v1",
            input_text="input",
            result=result,
        )

        assert PodcastHostExtraction.objects.get(podcast=podcast).input_tokens == 10
        assert HostCandidate.objects.filter(name="Jane Doe", kind=HostCandidate.Kind.HOST).exists()
        assert HostCandidate.objects.filter(
            name="John Smith",
            kind=HostCandidate.Kind.COHOST,
        ).exists()

    def test_host_kind_accepts_expected_labels(self) -> None:
        assert host_kind("host") == HostCandidate.Kind.HOST
        assert host_kind("co-host") == HostCandidate.Kind.COHOST
        assert host_kind("sidekick") == HostCandidate.Kind.COHOST
        assert host_kind("guest") == ""
