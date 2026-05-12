from __future__ import annotations

import os

from openai import AsyncOpenAI, OpenAI

from podcast_network.extraction.host_models import (
    ExtractedPodcastHostResult,
    PodcastHostExtractionResponse,
    PodcastHostExtractionResult,
)
from podcast_network.extraction.host_prompt import PodcastHostPrompt
from podcast_network.extraction.openai_client import MissingOpenAIKeyError


class OpenAIPodcastHostExtractor:
    def __init__(
        self,
        *,
        model: str = "gpt-5-mini",
        reasoning_effort: str = "medium",
        web_search: bool = False,
        max_tool_calls: int | None = None,
    ) -> None:
        if not os.environ.get("OPENAI_API_KEY"):
            raise MissingOpenAIKeyError("OPENAI_API_KEY is not set.")
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.web_search = web_search
        self.max_tool_calls = max_tool_calls
        self.client = OpenAI()
        self.async_client = AsyncOpenAI()

    def extract(self, prompt: PodcastHostPrompt) -> PodcastHostExtractionResult:
        response = self.client.responses.parse(
            model=self.model,
            instructions=prompt.instructions,
            input=prompt.input_text,
            text_format=PodcastHostExtractionResponse,
            max_output_tokens=1200,
            reasoning={"effort": self.reasoning_effort},
            **self.tool_options(),
        )
        return response_to_result(response)

    async def extract_async(self, prompt: PodcastHostPrompt) -> PodcastHostExtractionResult:
        response = await self.async_client.responses.parse(
            model=self.model,
            instructions=prompt.instructions,
            input=prompt.input_text,
            text_format=PodcastHostExtractionResponse,
            max_output_tokens=1200,
            reasoning={"effort": self.reasoning_effort},
            **self.tool_options(),
        )
        return response_to_result(response)

    def tool_options(self) -> dict:
        if not self.web_search:
            return {}
        options: dict = {
            "tools": [{"type": "web_search"}],
            "tool_choice": "auto",
        }
        if self.max_tool_calls is not None:
            options["max_tool_calls"] = self.max_tool_calls
        return options


def response_to_result(response) -> PodcastHostExtractionResult:
    parsed = response.output_parsed
    if parsed is None:
        raise RuntimeError("OpenAI response did not contain parsed structured output.")
    usage = getattr(response, "usage", None)
    return PodcastHostExtractionResult(
        hosts=[
            ExtractedPodcastHostResult(
                name=host.name.strip(),
                kind=host.kind.strip().lower(),
                confidence=host.confidence,
                evidence=host.evidence.strip(),
            )
            for host in parsed.hosts
            if host.name.strip()
        ],
        raw_response={
            "id": response.id,
            "model": response.model,
            "output_text": response.output_text,
        },
        input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
        output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
    )
