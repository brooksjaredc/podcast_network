from __future__ import annotations

import os

from openai import AsyncOpenAI, OpenAI

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
    def __init__(
        self,
        *,
        model: str = DEFAULT_EXTRACTION_MODEL,
        reasoning_effort: str = "minimal",
    ) -> None:
        if not os.environ.get("OPENAI_API_KEY"):
            raise MissingOpenAIKeyError("OPENAI_API_KEY is not set.")
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.client = OpenAI()
        self.async_client = AsyncOpenAI()

    def extract(self, prompt: EpisodePrompt) -> GuestExtractionResult:
        response = self.client.responses.parse(
            model=self.model,
            instructions=prompt.instructions,
            input=prompt.input_text,
            text_format=GuestExtractionResponse,
            max_output_tokens=4000,
            reasoning={"effort": self.reasoning_effort},
        )
        return response_to_result(response)

    async def extract_async(self, prompt: EpisodePrompt) -> GuestExtractionResult:
        response = await self.async_client.responses.parse(
            model=self.model,
            instructions=prompt.instructions,
            input=prompt.input_text,
            text_format=GuestExtractionResponse,
            max_output_tokens=4000,
            reasoning={"effort": self.reasoning_effort},
        )
        return response_to_result(response)


def response_to_result(response) -> GuestExtractionResult:
    parsed = response.output_parsed
    if parsed is None:
        raise RuntimeError("OpenAI response did not contain parsed structured output.")

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
        raw_response={
            "id": response.id,
            "model": response.model,
            "output_text": response.output_text,
        },
        input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
        output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
    )
