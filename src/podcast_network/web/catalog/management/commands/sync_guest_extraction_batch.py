from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from openai import OpenAI

from podcast_network.cloud_artifacts import parse_gcs_uri, upload_text_to_gcs
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

        output_text = download_file_text(client, batch.output_file_id)
        output_path, output_gcs_uri = write_batch_artifact(
            run=run,
            filename="output.jsonl",
            text=output_text,
        )

        error_path = ""
        error_gcs_uri = ""
        if batch.error_file_id:
            error_path_obj, error_gcs_uri = write_batch_artifact(
                run=run,
                filename="errors.jsonl",
                text=download_file_text(client, batch.error_file_id),
            )
            error_path = str(error_path_obj)

        outcomes = sync_output_lines(run=run, output_text=output_text)
        metadata = {
            **run.metadata,
            "output_file_id": batch.output_file_id,
            "output_jsonl_path": str(output_path),
        }
        if output_gcs_uri:
            metadata["output_jsonl_gcs_uri"] = output_gcs_uri
        if batch.error_file_id:
            metadata["error_file_id"] = batch.error_file_id
            metadata["error_jsonl_path"] = error_path
            if error_gcs_uri:
                metadata["error_jsonl_gcs_uri"] = error_gcs_uri
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


def write_batch_artifact(
    *,
    run: ExtractionRun,
    filename: str,
    text: str,
) -> tuple[Path, str]:
    path = output_file_path(run, filename)
    path.write_text(text, encoding="utf-8")
    gcs_uri = batch_artifact_gcs_uri(run=run, filename=filename)
    if gcs_uri:
        upload_text_to_gcs(text=text, gcs_uri=gcs_uri, content_type="application/jsonl")
    return path, gcs_uri


def batch_artifact_gcs_uri(*, run: ExtractionRun, filename: str) -> str:
    prefix = str(run.metadata.get("batch_artifact_gcs_uri") or "").strip()
    if not prefix:
        return ""
    bucket_name, blob_prefix = parse_gcs_uri(prefix)
    run_label = safe_artifact_segment(
        str(
            run.metadata.get("coordinator_label")
            or run.metadata.get("run_label")
            or f"run-{run.id}"
        )
    )
    phase = safe_artifact_segment(str(run.metadata.get("phase") or "batch"))
    batch_id = safe_artifact_segment(str(run.metadata.get("batch_id") or f"run-{run.id}"))
    blob_name = "/".join(
        part.strip("/")
        for part in [
            blob_prefix,
            run_label,
            phase,
            f"run_{run.id}_{batch_id}",
            filename,
        ]
        if part.strip("/")
    )
    return f"gs://{bucket_name}/{blob_name}"


def safe_artifact_segment(value: str) -> str:
    safe = "".join(
        character if character.isalnum() or character in "-_." else "-"
        for character in value
    )
    return safe.strip("-") or "artifact"
