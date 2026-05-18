from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass

from asgiref.sync import sync_to_async
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
    run_label: str = "",
) -> ExtractionRun:
    metadata = {"run_label": run_label} if run_label else {}
    run = ExtractionRun.objects.create(
        model=model,
        provider=provider,
        prompt_version=prompt_version,
        episodes_requested=len(episodes),
        metadata=metadata,
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


async def extract_guest_batch_async(
    episodes: list[Episode],
    *,
    extractor,
    model: str,
    provider: str,
    prompt_version: str = PROMPT_VERSION,
    force: bool = False,
    concurrency: int = 10,
    run_label: str = "",
    retries: int = 2,
    retry_base_seconds: float = 1.0,
    requests_per_minute: int = 0,
) -> ExtractionRun:
    metadata = {
        "concurrency": concurrency,
        "retries": retries,
        "retry_base_seconds": retry_base_seconds,
        "requests_per_minute": requests_per_minute,
    }
    if run_label:
        metadata["run_label"] = run_label

    run = await sync_to_async(ExtractionRun.objects.create)(
        model=model,
        provider=provider,
        prompt_version=prompt_version,
        episodes_requested=len(episodes),
        metadata=metadata,
    )
    semaphore = asyncio.Semaphore(concurrency)
    rate_limiter = AsyncStartRateLimiter(requests_per_minute)

    async def extract_one(episode: Episode) -> EpisodeExtractionOutcome:
        if await sync_to_async(already_extracted)(
            episode=episode,
            model=model,
            prompt_version=prompt_version,
            force=force,
        ):
            return EpisodeExtractionOutcome(episode_id=episode.id, succeeded=True)

        prompt = await sync_to_async(build_episode_prompt)(episode)
        try:
            async with semaphore:
                await rate_limiter.acquire()
                result = await extract_async_with_retries(
                    extractor=extractor,
                    prompt=prompt,
                    retries=retries,
                    retry_base_seconds=retry_base_seconds,
                )
        except Exception as exc:
            return await sync_to_async(persist_failed_extraction)(
                episode=episode,
                extraction_run=run,
                model=model,
                prompt_version=prompt_version,
                input_text=prompt.input_text,
                error=str(exc),
            )

        return await sync_to_async(persist_successful_extraction)(
            episode=episode,
            extraction_run=run,
            model=model,
            prompt_version=prompt_version,
            input_text=prompt.input_text,
            result=result,
        )

    outcomes = await asyncio.gather(*(extract_one(episode) for episode in episodes))
    return await sync_to_async(finalize_extraction_run)(run=run, outcomes=outcomes)


class AsyncStartRateLimiter:
    def __init__(self, requests_per_minute: int) -> None:
        self.interval_seconds = 60 / requests_per_minute if requests_per_minute else 0
        self.lock = asyncio.Lock()
        self.next_start = 0.0

    async def acquire(self) -> None:
        if not self.interval_seconds:
            return
        async with self.lock:
            now = time.monotonic()
            if now < self.next_start:
                await asyncio.sleep(self.next_start - now)
                now = time.monotonic()
            self.next_start = now + self.interval_seconds


async def extract_async_with_retries(
    *,
    extractor,
    prompt,
    retries: int,
    retry_base_seconds: float,
) -> GuestExtractionResult:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return await extractor.extract_async(prompt)
        except Exception as exc:
            last_error = exc
            if attempt >= retries:
                break
            await asyncio.sleep(retry_base_seconds * (2**attempt))

    if last_error is None:  # pragma: no cover - defensive only
        raise RuntimeError("Extraction failed without an exception.")
    raise last_error


def extract_episode_guests(
    episode: Episode,
    *,
    extractor,
    extraction_run: ExtractionRun,
    model: str,
    prompt_version: str = PROMPT_VERSION,
    force: bool = False,
) -> EpisodeExtractionOutcome:
    if already_extracted(
        episode=episode,
        model=model,
        prompt_version=prompt_version,
        force=force,
    ):
        return EpisodeExtractionOutcome(episode_id=episode.id, succeeded=True)

    prompt = build_episode_prompt(episode)
    try:
        result = extractor.extract(prompt)
    except Exception as exc:
        return persist_failed_extraction(
            episode=episode,
            extraction_run=extraction_run,
            model=model,
            prompt_version=prompt_version,
            input_text=prompt.input_text,
            error=str(exc),
        )

    return persist_successful_extraction(
        episode=episode,
        extraction_run=extraction_run,
        model=model,
        prompt_version=prompt_version,
        input_text=prompt.input_text,
        result=result,
    )


def already_extracted(
    *,
    episode: Episode,
    model: str,
    prompt_version: str,
    force: bool,
) -> bool:
    if force:
        return False
    return EpisodeGuestExtraction.objects.filter(
        episode=episode,
        model=model,
        prompt_version=prompt_version,
        status=EpisodeGuestExtraction.Status.SUCCEEDED,
    ).exists()


def persist_failed_extraction(
    *,
    episode: Episode,
    extraction_run: ExtractionRun,
    model: str,
    prompt_version: str,
    input_text: str,
    error: str,
) -> EpisodeExtractionOutcome:
    EpisodeGuestExtraction.objects.update_or_create(
        episode=episode,
        prompt_version=prompt_version,
        model=model,
        defaults={
            "extraction_run": extraction_run,
            "status": EpisodeGuestExtraction.Status.FAILED,
            "input_text": sanitize_postgres_text(input_text),
            "error": sanitize_postgres_text(error),
        },
    )
    return EpisodeExtractionOutcome(episode_id=episode.id, succeeded=False, error=error)


def persist_successful_extraction(
    *,
    episode: Episode,
    extraction_run: ExtractionRun,
    model: str,
    prompt_version: str,
    input_text: str,
    result: GuestExtractionResult,
) -> EpisodeExtractionOutcome:
    with transaction.atomic():
        extraction, _ = EpisodeGuestExtraction.objects.update_or_create(
            episode=episode,
            prompt_version=prompt_version,
            model=model,
            defaults={
                "extraction_run": extraction_run,
                "status": EpisodeGuestExtraction.Status.SUCCEEDED,
                "input_text": sanitize_postgres_text(input_text),
                "raw_response": sanitize_json_for_postgres(result.raw_response),
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


def finalize_extraction_run(
    *,
    run: ExtractionRun,
    outcomes: list[EpisodeExtractionOutcome],
) -> ExtractionRun:
    input_tokens = 0
    output_tokens = 0
    for extraction in run.episode_extractions.all():
        input_tokens += extraction.input_tokens
        output_tokens += extraction.output_tokens

    run.episodes_succeeded = sum(outcome.succeeded for outcome in outcomes)
    run.episodes_failed = sum(not outcome.succeeded for outcome in outcomes)
    run.input_tokens = input_tokens
    run.output_tokens = output_tokens
    run.finished_at = timezone.now()
    if run.episodes_failed and run.episodes_succeeded:
        run.status = ExtractionRun.Status.PARTIAL
    elif run.episodes_failed:
        run.status = ExtractionRun.Status.FAILED
    else:
        run.status = ExtractionRun.Status.SUCCEEDED
    run.save()
    return run


def create_guest_candidates(
    extraction: EpisodeGuestExtraction,
    result: GuestExtractionResult,
) -> None:
    GuestCandidate.objects.bulk_create(
        [
            GuestCandidate(
                extraction=extraction,
                name=sanitize_postgres_text(guest.name),
                normalized_name=normalize_name(sanitize_postgres_text(guest.name)),
                confidence=guest.confidence,
                evidence=sanitize_postgres_text(guest.evidence),
            )
            for guest in result.guests
        ]
    )


def normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def sanitize_postgres_text(value: str) -> str:
    return value.replace("\x00", "")


def sanitize_json_for_postgres(value):
    if isinstance(value, str):
        return sanitize_postgres_text(value)
    if isinstance(value, list):
        return [sanitize_json_for_postgres(item) for item in value]
    if isinstance(value, dict):
        return {
            sanitize_postgres_text(str(key)): sanitize_json_for_postgres(item)
            for key, item in value.items()
        }
    return value
