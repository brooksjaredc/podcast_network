from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field


class ExtractedGuest(BaseModel):
    name: str = Field(description="Full display name of the guest or interviewee.")
    confidence: float = Field(ge=0, le=1, description="Confidence that this person is a guest.")
    evidence: str = Field(description="Short text span or reason supporting the extraction.")


class GuestExtractionResponse(BaseModel):
    guests: list[ExtractedGuest] = Field(default_factory=list)


@dataclass(frozen=True)
class ExtractedGuestResult:
    name: str
    confidence: float
    evidence: str = ""


@dataclass(frozen=True)
class GuestExtractionResult:
    guests: list[ExtractedGuestResult] = field(default_factory=list)
    raw_response: dict = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
