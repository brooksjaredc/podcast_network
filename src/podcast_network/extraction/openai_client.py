from __future__ import annotations

import os

from openai import OpenAI

from podcast_network.extraction.models import (
    ExtractedGuestResult,
    GuestExtractionResponse,
    GuestExtractionResult,
)
from podcast_network.extraction.prompt import EpisodePrompt

DEFAULT_EXTRACTION_MODEL = "gpt-5-nano"


class MissingOpenAIKeyError(RuntimeError):
    pass


class OpenAIGuestExtractor:
    def __init__(self, *, model: str = DEFAULT_EXTRACTION_MODEL) -> None:
        if not os.environ.get("OPENAI_API_KEY"):
            raise MissingOpenAIKeyError("OPENAI_API_KEY is not set.")
        self.model = model
        self.client = OpenAI()

    def extract(self, prompt: EpisodePrompt) -> GuestExtractionResult:
        response = self.client.responses.parse(
            model=self.model,
            instructions=prompt.instructions,
            input=prompt.input_text,
            text_format=GuestExtractionResponse,
            max_output_tokens=600,
        )
        parsed = response.output_parsed
        usage = getattr(response, "usage", None)
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
            raw_response=response.model_dump(mode="json"),
            input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
        )
