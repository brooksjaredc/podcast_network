from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from openai import OpenAI

from podcast_network.extraction.batch import (
    episode_id_from_custom_id,
    result_from_response_body,
)
from podcast_network.extraction.pipeline import (
    EpisodeExtractionOutcome,
    finalize_extraction_run,
    persist_failed_extraction,
    persist_successful_extraction,
)
from podcast_network.extraction.prompt import build_episode_prompt
from podcast_network.web.catalog.models import Episode, ExtractionRun


class Command(BaseCommand):
    help = "Download and persist completed OpenAI Batch API guest extraction results."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--run-id", type=int, required=True)

    def handle(self, *args: object, **options: object) -> None:
        run = ExtractionRun.objects.get(id=int(options["run_id"]))
        batch_id = run.metadata.get("batch_id")
        if not batch_id:
            raise CommandError(f"ExtractionRun {run.id} has no batch_id metadata.")

        client = OpenAI()
        batch = client.batches.retrieve(str(batch_id))
        if batch.status != "completed":
            self.stdout.write(
                self.style.WARNING(
                    f"Batch {batch.id} is {batch.status}; nothing to sync yet."
                )
            )
            return
        if not batch.output_file_id:
            raise CommandError(f"Batch {batch.id} completed without an output_file_id.")

        output_path = output_file_path(run, "output.jsonl")
        output_text = download_file_text(client, batch.output_file_id)
        output_path.write_text(output_text, encoding="utf-8")

        error_path = ""
        if batch.error_file_id:
            error_path_obj = output_file_path(run, "errors.jsonl")
            error_path_obj.write_text(
                download_file_text(client, batch.error_file_id),
                encoding="utf-8",
            )
            error_path = str(error_path_obj)

        outcomes = sync_output_lines(run=run, output_text=output_text)
        metadata = {
            **run.metadata,
            "output_file_id": batch.output_file_id,
            "output_jsonl_path": str(output_path),
        }
        if batch.error_file_id:
            metadata["error_file_id"] = batch.error_file_id
            metadata["error_jsonl_path"] = error_path
        run.metadata = metadata
        run.save(update_fields=["metadata"])
        finalize_extraction_run(run=run, outcomes=outcomes)
        self.stdout.write(
            self.style.SUCCESS(
                f"Synced run {run.id}: {run.episodes_succeeded} succeeded, "
                f"{run.episodes_failed} failed. Output: {output_path}"
            )
        )


def sync_output_lines(*, run: ExtractionRun, output_text: str) -> list[EpisodeExtractionOutcome]:
    outcomes = []
    for line in output_text.splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        outcomes.append(sync_output_record(run=run, record=record))
    return outcomes


def sync_output_record(
    *,
    run: ExtractionRun,
    record: dict[str, Any],
) -> EpisodeExtractionOutcome:
    episode_id = episode_id_from_custom_id(str(record["custom_id"]))
    episode = Episode.objects.get(id=episode_id)
    prompt = build_episode_prompt(episode)
    if record.get("error"):
        return persist_failed_extraction(
            episode=episode,
            extraction_run=run,
            model=run.model,
            prompt_version=run.prompt_version,
            input_text=prompt.input_text,
            error=json.dumps(record["error"]),
        )

    response = record.get("response") or {}
    status_code = int(response.get("status_code") or 0)
    if status_code != 200:
        return persist_failed_extraction(
            episode=episode,
            extraction_run=run,
            model=run.model,
            prompt_version=run.prompt_version,
            input_text=prompt.input_text,
            error=json.dumps(response),
        )

    try:
        result = result_from_response_body(response.get("body") or {})
    except Exception as exc:
        return persist_failed_extraction(
            episode=episode,
            extraction_run=run,
            model=run.model,
            prompt_version=run.prompt_version,
            input_text=prompt.input_text,
            error=str(exc),
        )

    return persist_successful_extraction(
        episode=episode,
        extraction_run=run,
        model=run.model,
        prompt_version=run.prompt_version,
        input_text=prompt.input_text,
        result=result,
    )


def download_file_text(client: OpenAI, file_id: str) -> str:
    response = client.files.content(file_id)
    if hasattr(response, "text"):
        return str(response.text)
    return response.read().decode("utf-8")


def output_file_path(run: ExtractionRun, filename: str) -> Path:
    base_path = Path(run.metadata.get("input_jsonl_path", "data/reports/batches/batch.jsonl"))
    output_dir = base_path.parent / f"run_{run.id}_{run.metadata.get('batch_id', 'batch')}"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / filename
