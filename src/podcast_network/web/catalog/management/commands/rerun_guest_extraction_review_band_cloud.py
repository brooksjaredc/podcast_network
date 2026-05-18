from __future__ import annotations

from django.db.models import Exists, OuterRef

from podcast_network.extraction.openai_client import DEFAULT_EXTRACTION_MODEL
from podcast_network.extraction.prompt import PROMPT_VERSION
from podcast_network.web.catalog.management.commands.run_guest_extraction_second_pass_cloud_backfill import (  # noqa: E501
    Command as SecondPassCommand,
)
from podcast_network.web.catalog.models import Episode, EpisodeGuestExtraction, GuestCandidate


class Command(SecondPassCommand):
    help = (
        "Rerun first-pass extraction for current medium-confidence review-band "
        "episodes, overwriting the same model/prompt extraction with a stronger "
        "reasoning effort."
    )

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=1000)
        parser.add_argument("--wave-size", type=int, default=4)
        parser.add_argument("--model", default=DEFAULT_EXTRACTION_MODEL)
        parser.add_argument("--prompt-version", default=PROMPT_VERSION)
        parser.add_argument("--reasoning-effort", default="low")
        parser.add_argument("--source-reasoning-effort", default="minimal")
        parser.add_argument("--review-min-confidence", type=float, default=0.75)
        parser.add_argument("--review-max-confidence", type=float, default=0.90)
        parser.add_argument(
            "--review-allow-high-confidence",
            action="store_true",
            help="Rerun episodes even when the current first pass has a high-confidence guest.",
        )
        parser.add_argument("--run-label", default="guest-extraction-cloud-low-rerun")
        parser.add_argument("--poll-interval-seconds", type=int, default=300)
        parser.add_argument("--max-runtime-seconds", type=int, default=82800)
        parser.add_argument("--openai-timeout-seconds", type=float, default=60.0)
        parser.add_argument(
            "--output-dir",
            default="/tmp/podcast-network-batches",
            help="Directory for temporary batch input and output files.",
        )

    def extraction_model(self, options: dict[str, object]) -> str:
        return str(options["model"])

    def extraction_reasoning_effort(self, options: dict[str, object]) -> str:
        return str(options["reasoning_effort"])

    def completion_message(self) -> str:
        return "Review-band first-pass rerun complete."

    def remaining_message(self) -> str:
        return "Remaining episodes needing first-pass rerun"

    def phase(self) -> str:
        return "first_pass_review_rerun"

    def select_episodes(self, *, limit: int, options: dict[str, object]):
        return list(
            rerun_review_episode_queryset(
                model=str(options["model"]),
                prompt_version=str(options["prompt_version"]),
                review_min_confidence=float(options["review_min_confidence"]),
                review_max_confidence=float(options["review_max_confidence"]),
                require_no_high_confidence=not options["review_allow_high_confidence"],
                source_reasoning_effort=str(options["source_reasoning_effort"]),
                exclude_reasoning_effort=str(options["reasoning_effort"]),
            )[:limit]
        )

    def count_remaining(self, *, options: dict[str, object]) -> int:
        return rerun_review_episode_queryset(
            model=str(options["model"]),
            prompt_version=str(options["prompt_version"]),
            review_min_confidence=float(options["review_min_confidence"]),
            review_max_confidence=float(options["review_max_confidence"]),
            require_no_high_confidence=not options["review_allow_high_confidence"],
            source_reasoning_effort=str(options["source_reasoning_effort"]),
            exclude_reasoning_effort=str(options["reasoning_effort"]),
        ).count()


def rerun_review_episode_queryset(
    *,
    model: str,
    prompt_version: str,
    review_min_confidence: float,
    review_max_confidence: float,
    require_no_high_confidence: bool,
    source_reasoning_effort: str,
    exclude_reasoning_effort: str,
):
    current_extractions = EpisodeGuestExtraction.objects.filter(
        episode=OuterRef("pk"),
        model=model,
        prompt_version=prompt_version,
        status=EpisodeGuestExtraction.Status.SUCCEEDED,
        extraction_run__metadata__reasoning_effort=source_reasoning_effort,
    ).exclude(extraction_run__metadata__reasoning_effort=exclude_reasoning_effort)
    review_candidates = GuestCandidate.objects.filter(
        extraction__episode=OuterRef("pk"),
        extraction__model=model,
        extraction__prompt_version=prompt_version,
        extraction__status=EpisodeGuestExtraction.Status.SUCCEEDED,
        extraction__extraction_run__metadata__reasoning_effort=source_reasoning_effort,
        confidence__gte=review_min_confidence,
        confidence__lt=review_max_confidence,
    ).exclude(extraction__extraction_run__metadata__reasoning_effort=exclude_reasoning_effort)
    high_confidence_candidates = GuestCandidate.objects.filter(
        extraction__episode=OuterRef("pk"),
        extraction__model=model,
        extraction__prompt_version=prompt_version,
        extraction__status=EpisodeGuestExtraction.Status.SUCCEEDED,
        extraction__extraction_run__metadata__reasoning_effort=source_reasoning_effort,
        confidence__gte=review_max_confidence,
    ).exclude(extraction__extraction_run__metadata__reasoning_effort=exclude_reasoning_effort)
    queryset = (
        Episode.objects.select_related("podcast")
        .filter(Exists(current_extractions), Exists(review_candidates))
        .order_by("-published_at", "id")
    )
    if require_no_high_confidence:
        queryset = queryset.exclude(Exists(high_confidence_candidates))
    return queryset
