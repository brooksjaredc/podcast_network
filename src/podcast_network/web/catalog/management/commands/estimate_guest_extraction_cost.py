from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandParser
from django.db.models import Exists, OuterRef

from podcast_network.extraction.openai_client import DEFAULT_EXTRACTION_MODEL
from podcast_network.extraction.prompt import GUEST_EXTRACTION_INSTRUCTIONS, build_episode_prompt
from podcast_network.web.catalog.management.commands.extract_guests import (
    podcast_skips_guest_extraction,
)
from podcast_network.web.catalog.models import Episode, EpisodeGuestExtraction

CHARS_PER_TOKEN = 4

MODEL_PRICING_PER_MILLION = {
    DEFAULT_EXTRACTION_MODEL: {"input": 0.05, "output": 0.40},
    "gpt-5-mini": {"input": 0.25, "output": 2.00},
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
        parser.add_argument(
            "--new-episodes-only",
            action="store_true",
            help="Only estimate episodes with no successful guest extraction.",
        )
        parser.add_argument(
            "--batch-api",
            action="store_true",
            help="Apply the Batch API 50% discount to the estimate.",
        )
        parser.add_argument(
            "--second-pass-share",
            type=float,
            default=0.0,
            help="Expected share of first-pass episodes that will need second pass.",
        )
        parser.add_argument("--second-pass-model", default="gpt-5-mini")
        parser.add_argument("--second-pass-output-tokens", type=int, default=120)

    def handle(self, *args: object, **options: object) -> None:
        model = str(options["model"])
        estimate = estimate_cost(
            model=model,
            limit=int(options["limit"]),
            assumed_output_tokens=int(options["assumed_output_tokens"]),
            new_episodes_only=bool(options["new_episodes_only"]),
            batch_api=bool(options["batch_api"]),
        )
        self.stdout.write(
            "First-pass guest extraction estimate: "
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

        second_pass_share = float(options["second_pass_share"])
        if second_pass_share <= 0 or estimate.episodes == 0:
            return

        second_pass_episodes = round(estimate.episodes * second_pass_share)
        second_pass_estimate = estimate_cost(
            model=str(options["second_pass_model"]),
            limit=second_pass_episodes,
            assumed_output_tokens=int(options["second_pass_output_tokens"]),
            new_episodes_only=bool(options["new_episodes_only"]),
            batch_api=bool(options["batch_api"]),
        )
        self.stdout.write(
            "Expected second-pass estimate: "
            f"{second_pass_episodes} episodes at {second_pass_share:.1%}, "
            f"~{second_pass_estimate.input_tokens:,} input tokens, "
            f"~{second_pass_estimate.output_tokens:,} output tokens."
        )
        if second_pass_estimate.estimated_cost is not None:
            total = (estimate.estimated_cost or 0) + second_pass_estimate.estimated_cost
            self.stdout.write(
                f"Estimated combined API cost: ${total:,.2f} "
                f"(${estimate.estimated_cost:,.2f} first pass + "
                f"${second_pass_estimate.estimated_cost:,.2f} expected second pass)"
            )


def estimate_cost(
    *,
    model: str,
    limit: int,
    assumed_output_tokens: int,
    new_episodes_only: bool,
    batch_api: bool,
) -> CostEstimate:
    episodes = 0
    input_tokens = 0
    for episode in iter_estimate_episodes(
        limit=limit,
        new_episodes_only=new_episodes_only,
    ):
        episodes += 1
        prompt = build_episode_prompt(episode)
        input_tokens += estimate_tokens(GUEST_EXTRACTION_INSTRUCTIONS)
        input_tokens += estimate_tokens(prompt.input_text)
    output_tokens = episodes * assumed_output_tokens
    pricing = MODEL_PRICING_PER_MILLION.get(model)
    estimated_cost = None
    if pricing and pricing["input"] and pricing["output"]:
        estimated_cost = (
            input_tokens / 1_000_000 * pricing["input"]
            + output_tokens / 1_000_000 * pricing["output"]
        )
        if batch_api:
            estimated_cost *= 0.5
    return CostEstimate(
        episodes=episodes,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost=estimated_cost,
    )


def iter_estimate_episodes(*, limit: int, new_episodes_only: bool) -> Iterator[Episode]:
    queryset = Episode.objects.select_related("podcast").order_by("-published_at", "id")
    if new_episodes_only:
        successful_extraction = EpisodeGuestExtraction.objects.filter(
            episode=OuterRef("pk"),
            status=EpisodeGuestExtraction.Status.SUCCEEDED,
        )
        queryset = queryset.exclude(Exists(successful_extraction))

    selected = 0
    for episode in queryset.iterator(chunk_size=1000):
        if podcast_skips_guest_extraction(episode.podcast):
            continue
        yield episode
        selected += 1
        if limit > 0 and selected >= limit:
            break


def estimate_tokens(value: str) -> int:
    return max(1, len(value) // CHARS_PER_TOKEN)
