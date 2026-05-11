from __future__ import annotations

from django.test import TestCase

from podcast_network.extraction.single_name_prompt import build_single_name_resolution_prompt
from podcast_network.web.catalog.management.commands.resolve_single_name_guests import (
    select_single_name_episodes,
)
from podcast_network.web.catalog.models import (
    Episode,
    EpisodeGuestExtraction,
    ExtractionRun,
    GuestCandidate,
    Podcast,
)


class SingleNameResolutionTests(TestCase):
    def test_selector_finds_single_name_first_pass_candidates(self) -> None:
        episode = create_extracted_episode(candidate_name="Mike", normalized_name="mike")

        selected = select_single_name_episodes(
            episode_ids=[],
            limit=10,
            model="gpt-5-nano",
            prompt_version="guest-single-name-resolution-v1",
            first_pass_model="gpt-5-nano",
            first_pass_prompt_version="guest-extraction-v5",
            force=False,
        )

        assert [item.episode for item in selected] == [episode]
        assert selected[0].candidates[0].name == "Mike"

    def test_selector_excludes_already_resolved_episodes(self) -> None:
        episode = create_extracted_episode(candidate_name="Mike", normalized_name="mike")
        run = ExtractionRun.objects.create(
            model="gpt-5-nano",
            provider="fake",
            prompt_version="guest-single-name-resolution-v1",
            episodes_requested=1,
        )
        EpisodeGuestExtraction.objects.create(
            episode=episode,
            extraction_run=run,
            status=EpisodeGuestExtraction.Status.SUCCEEDED,
            prompt_version="guest-single-name-resolution-v1",
            model="gpt-5-nano",
            input_text="",
        )

        selected = select_single_name_episodes(
            episode_ids=[],
            limit=10,
            model="gpt-5-nano",
            prompt_version="guest-single-name-resolution-v1",
            first_pass_model="gpt-5-nano",
            first_pass_prompt_version="guest-extraction-v5",
            force=False,
        )

        assert selected == []

    def test_prompt_includes_candidates_and_episode_context(self) -> None:
        episode = create_extracted_episode(candidate_name="Mike", normalized_name="mike")
        selected = select_single_name_episodes(
            episode_ids=[],
            limit=10,
            model="gpt-5-nano",
            prompt_version="guest-single-name-resolution-v1",
            first_pass_model="gpt-5-nano",
            first_pass_prompt_version="guest-extraction-v5",
            force=False,
        )[0]

        prompt = build_single_name_resolution_prompt(episode, selected.candidates)

        assert "One-word candidates to resolve:" in prompt.input_text
        assert "- Mike" in prompt.input_text
        assert "Episode title: Episode with Mike" in prompt.input_text
        assert "Resolve underspecified one-word podcast guest names" in prompt.instructions


def create_extracted_episode(*, candidate_name: str, normalized_name: str) -> Episode:
    podcast = Podcast.objects.create(name="Example Podcast")
    episode = Episode.objects.create(
        podcast=podcast,
        guid="episode-1",
        title=f"Episode with {candidate_name}",
        description=f"Today {candidate_name} joins the show.",
    )
    run = ExtractionRun.objects.create(
        model="gpt-5-nano",
        provider="fake",
        prompt_version="guest-extraction-v5",
        episodes_requested=1,
    )
    extraction = EpisodeGuestExtraction.objects.create(
        episode=episode,
        extraction_run=run,
        status=EpisodeGuestExtraction.Status.SUCCEEDED,
        prompt_version="guest-extraction-v5",
        model="gpt-5-nano",
        input_text="",
    )
    GuestCandidate.objects.create(
        extraction=extraction,
        name=candidate_name,
        normalized_name=normalized_name,
        confidence=0.99,
        evidence=f"{candidate_name} joins the show",
    )
    return episode
