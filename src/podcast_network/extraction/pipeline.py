from __future__ import annotations

import re
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from podcast_network.extraction.models import GuestExtractionResult
from podcast_network.extraction.prompt import PROMPT_VERSION, build_episode_prompt
from podcast_network.web.catalog.models import (
    Episode,
    EpisodeGuestExtraction,
    ExtractionRun,
    GuestCandidate,
)


@dataclass(frozen=True)
class EpisodeExtractionOutcome:
    episode_id: int
    succeeded: bool
    guests_count: int = 0
    error: str = ""


def extract_guest_batch(
    episodes: list[Episode],
    *,
    extractor,
    model: str,
    provider: str,
    prompt_version: str = PROMPT_VERSION,
    force: bool = False,
) -> ExtractionRun:
    run = ExtractionRun.objects.create(
        model=model,
        provider=provider,
        prompt_version=prompt_version,
        episodes_requested=len(episodes),
    )
    succeeded = 0
    failed = 0
    input_tokens = 0
    output_tokens = 0
    for episode in episodes:
        outcome = extract_episode_guests(
            episode,
            extractor=extractor,
            extraction_run=run,
            model=model,
            prompt_version=prompt_version,
            force=force,
        )
        if outcome.succeeded:
            succeeded += 1
        else:
            failed += 1

    for extraction in run.episode_extractions.all():
        input_tokens += extraction.input_tokens
        output_tokens += extraction.output_tokens

    run.episodes_succeeded = succeeded
    run.episodes_failed = failed
    run.input_tokens = input_tokens
    run.output_tokens = output_tokens
    run.finished_at = timezone.now()
    if failed and succeeded:
        run.status = ExtractionRun.Status.PARTIAL
    elif failed:
        run.status = ExtractionRun.Status.FAILED
    else:
        run.status = ExtractionRun.Status.SUCCEEDED
    run.save()
    return run


def extract_episode_guests(
    episode: Episode,
    *,
    extractor,
    extraction_run: ExtractionRun,
    model: str,
    prompt_version: str = PROMPT_VERSION,
    force: bool = False,
) -> EpisodeExtractionOutcome:
    if not force and EpisodeGuestExtraction.objects.filter(
        episode=episode,
        model=model,
        prompt_version=prompt_version,
        status=EpisodeGuestExtraction.Status.SUCCEEDED,
    ).exists():
        return EpisodeExtractionOutcome(episode_id=episode.id, succeeded=True)

    prompt = build_episode_prompt(episode)
    try:
        result = extractor.extract(prompt)
    except Exception as exc:
        EpisodeGuestExtraction.objects.update_or_create(
            episode=episode,
            prompt_version=prompt_version,
            model=model,
            defaults={
                "extraction_run": extraction_run,
                "status": EpisodeGuestExtraction.Status.FAILED,
                "input_text": prompt.input_text,
                "error": str(exc),
            },
        )
        return EpisodeExtractionOutcome(episode_id=episode.id, succeeded=False, error=str(exc))

    with transaction.atomic():
        extraction, _ = EpisodeGuestExtraction.objects.update_or_create(
            episode=episode,
            prompt_version=prompt_version,
            model=model,
            defaults={
                "extraction_run": extraction_run,
                "status": EpisodeGuestExtraction.Status.SUCCEEDED,
                "input_text": prompt.input_text,
                "raw_response": result.raw_response,
                "error": "",
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
            },
        )
        extraction.guest_candidates.all().delete()
        create_guest_candidates(extraction, result)
    return EpisodeExtractionOutcome(
        episode_id=episode.id,
        succeeded=True,
        guests_count=len(result.guests),
    )


def create_guest_candidates(
    extraction: EpisodeGuestExtraction,
    result: GuestExtractionResult,
) -> None:
    GuestCandidate.objects.bulk_create(
        [
            GuestCandidate(
                extraction=extraction,
                name=guest.name,
                normalized_name=normalize_name(guest.name),
                confidence=guest.confidence,
                evidence=guest.evidence,
            )
            for guest in result.guests
        ]
    )


def normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
