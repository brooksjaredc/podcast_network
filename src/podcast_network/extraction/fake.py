from __future__ import annotations

import re

from podcast_network.extraction.models import ExtractedGuestResult, GuestExtractionResult
from podcast_network.extraction.prompt import EpisodePrompt

WITH_PATTERN = re.compile(
    r"\b(?:with|w/|featuring|guest)[ \t]+"
    r"([A-Z][A-Za-z.'-]+(?:[ \t]+[A-Z][A-Za-z.'-]+){1,3})"
)


class FakeGuestExtractor:
    """Cheap deterministic extractor for tests and command dry-runs."""

    def extract(self, prompt: EpisodePrompt) -> GuestExtractionResult:
        match = WITH_PATTERN.search(prompt.input_text)
        if not match:
            return GuestExtractionResult(raw_response={"provider": "fake", "guests": []})
        name = match.group(1).strip()
        return GuestExtractionResult(
            guests=[
                ExtractedGuestResult(
                    name=name,
                    confidence=0.75,
                    evidence=f"matched local pattern: {match.group(0)}",
                )
            ],
            raw_response={"provider": "fake", "guests": [{"name": name}]},
        )

    async def extract_async(self, prompt: EpisodePrompt) -> GuestExtractionResult:
        return self.extract(prompt)
