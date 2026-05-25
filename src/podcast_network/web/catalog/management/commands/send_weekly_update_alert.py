from __future__ import annotations

import json
from typing import Any
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from podcast_network.web.catalog.models import (
    ExtractionRun,
    FutureLinkPredictionRun,
    PipelineRun,
    ScrapeRun,
)


class Command(BaseCommand):
    help = "Send a compact weekly update alert payload to an optional webhook."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--run-label", required=True)
        parser.add_argument("--status", choices=["succeeded", "failed"], required=True)
        parser.add_argument("--webhook-url", default="")
        parser.add_argument("--error", default="")
        parser.add_argument("--require-webhook", action="store_true")

    def handle(self, *args: object, **options: object) -> None:
        webhook_url = str(options["webhook_url"] or settings.WEEKLY_UPDATE_ALERT_WEBHOOK_URL)
        payload = weekly_update_alert_payload(
            run_label=str(options["run_label"]),
            status=str(options["status"]),
            error=str(options["error"]),
        )
        self.stdout.write(json.dumps(payload, sort_keys=True))
        if not webhook_url:
            if options["require_webhook"]:
                raise CommandError("No weekly update alert webhook configured.")
            self.stdout.write(
                self.style.WARNING("No alert webhook configured; printed payload only.")
            )
            return
        post_json(webhook_url=webhook_url, payload=payload)
        self.stdout.write(self.style.SUCCESS("Weekly update alert sent."))


def weekly_update_alert_payload(
    *,
    run_label: str,
    status: str,
    error: str = "",
) -> dict[str, Any]:
    pipeline_run = PipelineRun.objects.filter(run_label=run_label).order_by("-started_at").first()
    scrape_run = ScrapeRun.objects.filter(run_label=run_label).order_by("-started_at").first()
    extraction_runs = ExtractionRun.objects.filter(
        provider="openai-batch",
        metadata__coordinator_label=run_label,
    )
    prediction_run = FutureLinkPredictionRun.objects.filter(run_id=run_label).first()
    failed_steps = []
    running_steps = []
    if pipeline_run is not None:
        failed_steps = [
            step.command
            for step in pipeline_run.steps.filter(status="failed").order_by("sequence")
        ]
        running_steps = [
            step.command
            for step in pipeline_run.steps.filter(status__in=["pending", "running"]).order_by(
                "sequence"
            )
        ]
    return {
        "run_label": run_label,
        "status": status,
        "error": error,
        "pipeline_status": pipeline_run.status if pipeline_run else "",
        "failed_steps": failed_steps,
        "running_steps": running_steps,
        "scrape": {
            "status": scrape_run.status if scrape_run else "",
            "requested": scrape_run.feeds_requested if scrape_run else 0,
            "succeeded": scrape_run.feeds_succeeded if scrape_run else 0,
            "failed": scrape_run.feeds_failed if scrape_run else 0,
        },
        "llm": {
            "runs": extraction_runs.count(),
            "episodes_requested": sum(run.episodes_requested for run in extraction_runs),
            "episodes_succeeded": sum(run.episodes_succeeded for run in extraction_runs),
            "episodes_failed": sum(run.episodes_failed for run in extraction_runs),
        },
        "predictions": {
            "candidate_count": prediction_run.candidate_count if prediction_run else 0,
            "rows_written": prediction_run.rows_written if prediction_run else 0,
        },
    }


def post_json(*, webhook_url: str, payload: dict[str, Any]) -> None:
    request = Request(
        webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=20) as response:
        if response.status >= 400:
            raise CommandError(f"Alert webhook returned HTTP {response.status}.")
