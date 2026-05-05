from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from podcast_network.extraction.models import (
    ExtractedGuestResult,
    GuestExtractionResponse,
    GuestExtractionResult,
)
from podcast_network.extraction.prompt import build_episode_prompt
from podcast_network.web.catalog.models import Episode

BATCH_ENDPOINT = "/v1/responses"
MAX_OUTPUT_TOKENS = 4000


def guest_extraction_json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "guests": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Full display name of the guest or interviewee.",
                        },
                        "confidence": {
                            "type": "number",
                            "description": "Confidence that this person is a guest.",
                        },
                        "evidence": {
                            "type": "string",
                            "description": "Short text span or reason supporting the extraction.",
                        },
                    },
                    "required": ["name", "confidence", "evidence"],
                },
            }
        },
        "required": ["guests"],
    }


def batch_custom_id(episode_id: int) -> str:
    return f"episode:{episode_id}"


def episode_id_from_custom_id(custom_id: str) -> int:
    prefix = "episode:"
    if not custom_id.startswith(prefix):
        raise ValueError(f"Unsupported batch custom_id: {custom_id}")
    return int(custom_id.removeprefix(prefix))


def build_batch_request(
    episode: Episode,
    *,
    model: str,
    reasoning_effort: str,
) -> dict[str, Any]:
    prompt = build_episode_prompt(episode)
    return {
        "custom_id": batch_custom_id(episode.id),
        "method": "POST",
        "url": BATCH_ENDPOINT,
        "body": {
            "model": model,
            "instructions": prompt.instructions,
            "input": prompt.input_text,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "guest_extraction",
                    "strict": True,
                    "schema": guest_extraction_json_schema(),
                }
            },
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "reasoning": {"effort": reasoning_effort},
        },
    }


def write_batch_jsonl(
    episodes: list[Episode],
    *,
    model: str,
    reasoning_effort: str,
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as jsonl_file:
        for episode in episodes:
            request = build_batch_request(
                episode,
                model=model,
                reasoning_effort=reasoning_effort,
            )
            jsonl_file.write(json.dumps(request, ensure_ascii=False) + "\n")


def result_from_response_body(body: dict[str, Any]) -> GuestExtractionResult:
    output_text = response_output_text(body)
    parsed = GuestExtractionResponse.model_validate_json(output_text)
    usage = body.get("usage") or {}
    return GuestExtractionResult(
        guests=[
            ExtractedGuestResult(
                name=guest.name.strip(),
                confidence=guest.confidence,
                evidence=guest.evidence.strip(),
            )
            for guest in parsed.guests
            if guest.name.strip()
        ],
        raw_response={
            "id": body.get("id", ""),
            "model": body.get("model", ""),
            "output_text": output_text,
        },
        input_tokens=int(usage.get("input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
    )


def response_output_text(body: dict[str, Any]) -> str:
    if body.get("output_text"):
        return str(body["output_text"])
    for output_item in body.get("output", []):
        if output_item.get("type") != "message":
            continue
        for content_item in output_item.get("content", []):
            if content_item.get("type") == "output_text":
                return str(content_item.get("text") or "")
    raise ValueError("Batch response body did not contain output text.")
