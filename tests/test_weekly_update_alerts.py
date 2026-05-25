from __future__ import annotations

from django.utils import timezone

from podcast_network.web.catalog.management.commands.send_weekly_update_alert import (
    weekly_update_alert_payload,
)
from podcast_network.web.catalog.models import (
    ExtractionRun,
    FutureLinkPredictionRun,
    PipelineRun,
    PipelineStepRun,
    ScrapeRun,
)


def test_weekly_update_alert_payload_summarizes_run_state() -> None:
    pipeline_run = PipelineRun.objects.create(
        run_label="weekly-update-alert-test",
        status=PipelineRun.Status.FAILED,
    )
    PipelineStepRun.objects.create(
        pipeline_run=pipeline_run,
        sequence=1,
        name="Scrape RSS feeds",
        command="ingest_feeds",
        status=PipelineStepRun.Status.FAILED,
    )
    ScrapeRun.objects.create(
        run_label="weekly-update-alert-test",
        status=ScrapeRun.Status.PARTIAL,
        feeds_requested=10,
        feeds_succeeded=8,
        feeds_failed=2,
    )
    ExtractionRun.objects.create(
        provider="openai-batch",
        model="gpt-5-nano",
        prompt_version="guest-extraction-v7",
        episodes_requested=5,
        episodes_succeeded=4,
        episodes_failed=1,
        metadata={"coordinator_label": "weekly-update-alert-test"},
    )
    FutureLinkPredictionRun.objects.create(
        run_id="weekly-update-alert-test",
        cutoff_at=timezone.now(),
        candidate_count=100,
        rows_written=10,
    )

    payload = weekly_update_alert_payload(
        run_label="weekly-update-alert-test",
        status="failed",
        error="boom",
    )

    assert payload["status"] == "failed"
    assert payload["error"] == "boom"
    assert payload["pipeline_status"] == PipelineRun.Status.FAILED
    assert payload["failed_steps"] == ["ingest_feeds"]
    assert payload["scrape"]["failed"] == 2
    assert payload["llm"]["episodes_succeeded"] == 4
    assert payload["predictions"]["rows_written"] == 10
