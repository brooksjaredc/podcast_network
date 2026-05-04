from __future__ import annotations

from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandParser

from podcast_network.extraction.openai_client import DEFAULT_EXTRACTION_MODEL
from podcast_network.extraction.prompt import GUEST_EXTRACTION_INSTRUCTIONS, build_episode_prompt
from podcast_network.web.catalog.models import Episode

CHARS_PER_TOKEN = 4

MODEL_PRICING_PER_MILLION = {
    DEFAULT_EXTRACTION_MODEL: {"input": 0.05, "output": 0.40},
}


@dataclass(frozen=True)
class CostEstimate:
    episodes: int
    input_tokens: int
    output_tokens: int
    estimated_cost: float | None


class Command(BaseCommand):
    help = "Estimate guest-extraction token volume before running LLM extraction."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--limit", type=int, default=1000)
        parser.add_argument("--model", default=DEFAULT_EXTRACTION_MODEL)
        parser.add_argument("--assumed-output-tokens", type=int, default=120)

    def handle(self, *args: object, **options: object) -> None:
        model = str(options["model"])
        estimate = estimate_cost(
            model=model,
            limit=int(options["limit"]),
            assumed_output_tokens=int(options["assumed_output_tokens"]),
        )
        self.stdout.write(
            "Guest extraction estimate: "
            f"{estimate.episodes} episodes, "
            f"~{estimate.input_tokens:,} input tokens, "
            f"~{estimate.output_tokens:,} output tokens."
        )
        if estimate.estimated_cost is None:
            self.stdout.write(
                self.style.WARNING(
                    "No local pricing configured for this model. "
                    "Use current OpenAI pricing before a full production run."
                )
            )
        else:
            self.stdout.write(f"Estimated API cost: ${estimate.estimated_cost:,.2f}")


def estimate_cost(*, model: str, limit: int, assumed_output_tokens: int) -> CostEstimate:
    episodes = list(Episode.objects.select_related("podcast").order_by("-published_at")[:limit])
    input_tokens = 0
    for episode in episodes:
        prompt = build_episode_prompt(episode)
        input_tokens += estimate_tokens(GUEST_EXTRACTION_INSTRUCTIONS)
        input_tokens += estimate_tokens(prompt.input_text)
    output_tokens = len(episodes) * assumed_output_tokens
    pricing = MODEL_PRICING_PER_MILLION.get(model)
    estimated_cost = None
    if pricing and pricing["input"] and pricing["output"]:
        estimated_cost = (
            input_tokens / 1_000_000 * pricing["input"]
            + output_tokens / 1_000_000 * pricing["output"]
        )
    return CostEstimate(
        episodes=len(episodes),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost=estimated_cost,
    )


def estimate_tokens(value: str) -> int:
    return max(1, len(value) // CHARS_PER_TOKEN)
