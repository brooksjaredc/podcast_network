from __future__ import annotations

import asyncio

from django.core.management import call_command
from django.test import TestCase, TransactionTestCase

from podcast_network.extraction.batch import build_batch_request
from podcast_network.extraction.fake import FakeGuestExtractor
from podcast_network.extraction.models import ExtractedGuestResult, GuestExtractionResult
from podcast_network.extraction.pipeline import (
    extract_guest_batch,
    extract_guest_batch_async,
)
from podcast_network.web.catalog.management.commands.sync_guest_extraction_batch import (
    sync_output_record,
)
from podcast_network.web.catalog.models import (
    Episode,
    EpisodeGuestExtraction,
    ExtractionRun,
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

    def test_backfill_command_resumes_from_successful_extractions(self) -> None:
        for index in range(3):
            create_episode(title=f"Episode {index} with Jane Doe")

        call_command(
            "backfill_guest_extractions",
            "--provider",
            "fake",
            "--model",
            "fake-model",
            "--batch-size",
            "2",
            "--max-batches",
            "1",
        )

        assert EpisodeGuestExtraction.objects.filter(
            model="fake-model",
            status=EpisodeGuestExtraction.Status.SUCCEEDED,
        ).count() == 2

        call_command(
            "backfill_guest_extractions",
            "--provider",
            "fake",
            "--model",
            "fake-model",
            "--batch-size",
            "2",
            "--max-batches",
            "1",
        )

        assert EpisodeGuestExtraction.objects.filter(
            model="fake-model",
            status=EpisodeGuestExtraction.Status.SUCCEEDED,
        ).count() == 3

    def test_backfill_dry_run_does_not_create_extractions(self) -> None:
        create_episode(title="Episode with Jane Doe")

        call_command(
            "backfill_guest_extractions",
            "--provider",
            "fake",
            "--model",
            "fake-model",
            "--batch-size",
            "1",
            "--dry-run",
        )

        assert EpisodeGuestExtraction.objects.count() == 0

    def test_backfill_command_can_run_second_pass_review_band(self) -> None:
        create_episode(title="Episode with Jane Doe")

        call_command(
            "backfill_guest_extractions",
            "--provider",
            "fake",
            "--model",
            "fake-model",
            "--batch-size",
            "1",
            "--max-batches",
            "1",
            "--second-pass-review-band",
            "--second-pass-provider",
            "fake",
            "--second-pass-model",
            "fake-review-model",
        )

        assert EpisodeGuestExtraction.objects.filter(
            model="fake-model",
            status=EpisodeGuestExtraction.Status.SUCCEEDED,
        ).count() == 1
        assert EpisodeGuestExtraction.objects.filter(
            model="fake-review-model",
            status=EpisodeGuestExtraction.Status.SUCCEEDED,
        ).count() == 1

    def test_batch_request_uses_responses_endpoint_and_custom_id(self) -> None:
        episode = create_episode(title="Episode with Jane Doe")

        request = build_batch_request(
            episode,
            model="gpt-5-nano",
            reasoning_effort="minimal",
        )

        assert request["custom_id"] == f"episode:{episode.id}"
        assert request["method"] == "POST"
        assert request["url"] == "/v1/responses"
        assert request["body"]["model"] == "gpt-5-nano"
        assert request["body"]["text"]["format"]["type"] == "json_schema"
        assert request["body"]["text"]["format"]["strict"] is True

    def test_sync_batch_output_record_persists_guest_candidates(self) -> None:
        episode = create_episode(title="Episode with Jane Doe")
        run = ExtractionRun.objects.create(
            model="gpt-5-nano",
            provider="openai-batch",
            prompt_version="guest-extraction-v4",
            episodes_requested=1,
        )
        record = {
            "custom_id": f"episode:{episode.id}",
            "response": {
                "status_code": 200,
                "body": {
                    "id": "resp_test",
                    "model": "gpt-5-nano",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": (
                                        '{"guests":[{"name":"Jane Doe",'
                                        '"confidence":0.91,"evidence":"with Jane Doe"}]}'
                                    ),
                                }
                            ],
                        }
                    ],
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                },
            },
        }

        outcome = sync_output_record(run=run, record=record)

        assert outcome.succeeded is True
        extraction = EpisodeGuestExtraction.objects.get(episode=episode, model="gpt-5-nano")
        assert extraction.input_tokens == 10
        assert extraction.output_tokens == 5
        assert GuestCandidate.objects.get(extraction=extraction).name == "Jane Doe"

    def test_submit_batch_dry_run_can_select_second_pass_review_band(self) -> None:
        episode = create_episode(title="Episode with Jane Doe")
        first_pass_run = extract_guest_batch(
            [episode],
            extractor=FakeGuestExtractor(),
            model="gpt-5-nano",
            provider="fake",
        )

        call_command(
            "submit_guest_extraction_batch",
            "--review-band-run-id",
            str(first_pass_run.id),
            "--review-source-model",
            "gpt-5-nano",
            "--model",
            "gpt-5-mini",
            "--batch-size",
            "10",
            "--dry-run",
        )


class AsyncGuestExtractionTests(TransactionTestCase):
    def test_async_extraction_respects_concurrency_and_persists_results(self) -> None:
        episodes = [create_episode(title=f"Episode {index} with Jane Doe") for index in range(5)]
        extractor = AsyncFakeGuestExtractor()

        run = asyncio.run(
            extract_guest_batch_async(
                episodes,
                extractor=extractor,
                model="async-fake-model",
                provider="fake",
                concurrency=2,
                requests_per_minute=6000,
            )
        )

        assert run.episodes_succeeded == 5
        assert run.episodes_failed == 0
        assert extractor.max_active == 2
        assert GuestCandidate.objects.filter(name="Jane Doe").count() == 5

    def test_async_extraction_throttles_request_starts(self) -> None:
        episodes = [create_episode(title=f"Episode {index} with Jane Doe") for index in range(3)]
        extractor = TimedAsyncFakeGuestExtractor()

        run = asyncio.run(
            extract_guest_batch_async(
                episodes,
                extractor=extractor,
                model="async-fake-model",
                provider="fake",
                concurrency=3,
                requests_per_minute=6000,
            )
        )

        assert run.episodes_succeeded == 3
        start_gaps = [
            second - first
            for first, second in zip(extractor.starts, extractor.starts[1:], strict=False)
        ]
        assert min(start_gaps) >= 0.008

    def test_async_extraction_retries_transient_failures(self) -> None:
        episode = create_episode(title="Episode with Jane Doe")
        extractor = FlakyAsyncFakeGuestExtractor()

        run = asyncio.run(
            extract_guest_batch_async(
                [episode],
                extractor=extractor,
                model="async-fake-model",
                provider="fake",
                concurrency=1,
                retries=1,
                retry_base_seconds=0,
                run_label="test-run",
            )
        )

        assert run.episodes_succeeded == 1
        assert run.metadata["run_label"] == "test-run"
        assert run.metadata["retries"] == 1
        assert extractor.calls == 2
        assert GuestCandidate.objects.filter(name="Jane Doe").count() == 1


class AsyncFakeGuestExtractor:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0

    async def extract_async(self, prompt) -> GuestExtractionResult:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        return GuestExtractionResult(
            guests=[
                ExtractedGuestResult(
                    name="Jane Doe",
                    confidence=0.9,
                    evidence="Synthetic async test guest.",
                )
            ],
            raw_response={},
            input_tokens=1,
            output_tokens=1,
        )


class FlakyAsyncFakeGuestExtractor:
    def __init__(self) -> None:
        self.calls = 0

    async def extract_async(self, prompt) -> GuestExtractionResult:
        self.calls += 1
        if self.calls == 1:
            raise TimeoutError("temporary timeout")
        return GuestExtractionResult(
            guests=[
                ExtractedGuestResult(
                    name="Jane Doe",
                    confidence=0.9,
                    evidence="Synthetic retry test guest.",
                )
            ],
            raw_response={},
            input_tokens=1,
            output_tokens=1,
        )


class TimedAsyncFakeGuestExtractor:
    def __init__(self) -> None:
        self.starts = []

    async def extract_async(self, prompt) -> GuestExtractionResult:
        loop = asyncio.get_running_loop()
        self.starts.append(loop.time())
        await asyncio.sleep(0)
        return GuestExtractionResult(
            guests=[
                ExtractedGuestResult(
                    name="Jane Doe",
                    confidence=0.9,
                    evidence="Synthetic throttle test guest.",
                )
            ],
            raw_response={},
            input_tokens=1,
            output_tokens=1,
        )


def create_episode(*, title: str) -> Episode:
    podcast = Podcast.objects.create(name=f"Example Podcast {title}")
    Feed.objects.create(podcast=podcast, url=f"https://example.com/{podcast.id}/rss")
    return Episode.objects.create(
        podcast=podcast,
        guid=title,
        title=title,
        description="A test episode.",
    )
