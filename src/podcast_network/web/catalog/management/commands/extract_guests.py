from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError, CommandParser

from podcast_network.extraction.fake import FakeGuestExtractor
from podcast_network.extraction.openai_client import (
    DEFAULT_EXTRACTION_MODEL,
    MissingOpenAIKeyError,
    OpenAIGuestExtractor,
)
from podcast_network.extraction.pipeline import extract_guest_batch
from podcast_network.extraction.prompt import PROMPT_VERSION
from podcast_network.web.catalog.models import Episode, EpisodeGuestExtraction


class Command(BaseCommand):
    help = "Extract episode guest names with an LLM-backed structured-output stage."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--limit", type=int, default=25)
        parser.add_argument("--episode-id", type=int, action="append", default=[])
        parser.add_argument("--model", default=DEFAULT_EXTRACTION_MODEL)
        parser.add_argument("--prompt-version", default=PROMPT_VERSION)
        parser.add_argument("--provider", choices=["openai", "fake"], default="fake")
        parser.add_argument("--reasoning-effort", default="minimal")
        parser.add_argument("--force", action="store_true")

    def handle(self, *args: object, **options: object) -> None:
        model = str(options["model"])
        prompt_version = str(options["prompt_version"])
        provider = str(options["provider"])
        episodes = select_episodes(
            episode_ids=list(options["episode_id"]),
            limit=int(options["limit"]),
            model=model,
            prompt_version=prompt_version,
            force=bool(options["force"]),
        )
        if not episodes:
            self.stdout.write(self.style.WARNING("No episodes selected for extraction."))
            return

        try:
            extractor = build_extractor(
                provider=provider,
                model=model,
                reasoning_effort=str(options["reasoning_effort"]),
            )
        except MissingOpenAIKeyError as exc:
            raise CommandError(str(exc)) from exc

        run = extract_guest_batch(
            episodes,
            extractor=extractor,
            model=model,
            provider=provider,
            prompt_version=prompt_version,
            force=bool(options["force"]),
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Extraction run {run.id} {run.status}: "
                f"{run.episodes_succeeded} succeeded, {run.episodes_failed} failed, "
                f"{run.input_tokens} input tokens, {run.output_tokens} output tokens."
            )
        )


def select_episodes(
    *,
    episode_ids: list[int],
    limit: int,
    model: str,
    prompt_version: str,
    force: bool,
) -> list[Episode]:
    queryset = Episode.objects.select_related("podcast").order_by("-published_at", "id")
    if episode_ids:
        queryset = queryset.filter(id__in=episode_ids)
        limit = max(limit, len(episode_ids))
    elif not force:
        queryset = queryset.exclude(
            guest_extractions__model=model,
            guest_extractions__prompt_version=prompt_version,
            guest_extractions__status=EpisodeGuestExtraction.Status.SUCCEEDED,
        )
    return list(queryset[:limit])


def build_extractor(*, provider: str, model: str, reasoning_effort: str):
    if provider == "fake":
        return FakeGuestExtractor()
    return OpenAIGuestExtractor(model=model, reasoning_effort=reasoning_effort)
