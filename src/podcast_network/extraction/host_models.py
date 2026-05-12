from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field


class ExtractedPodcastHost(BaseModel):
    name: str = Field(description="Full display name of the host or co-host.")
    kind: str = Field(description="Either 'host' or 'cohost'.")
    confidence: float = Field(ge=0, le=1)
    evidence: str = Field(description="Short text span or reason supporting the classification.")


class PodcastHostExtractionResponse(BaseModel):
    hosts: list[ExtractedPodcastHost] = Field(default_factory=list)


@dataclass(frozen=True)
class ExtractedPodcastHostResult:
    name: str
    kind: str
    confidence: float
    evidence: str = ""


@dataclass(frozen=True)
class PodcastHostExtractionResult:
    hosts: list[ExtractedPodcastHostResult] = field(default_factory=list)
    raw_response: dict = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
