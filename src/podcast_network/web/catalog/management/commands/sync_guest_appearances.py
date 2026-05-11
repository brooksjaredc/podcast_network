from __future__ import annotations

from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction

from podcast_network.extraction.pipeline import normalize_name
from podcast_network.web.catalog.models import (
    Appearance,
    EpisodeGuestExtraction,
    GuestCandidate,
    Person,
)


@dataclass
class SyncStats:
    episodes_seen: int = 0
    candidates_seen: int = 0
    people_created: int = 0
    appearances_created: int = 0
    appearances_updated: int = 0


class Command(BaseCommand):
    help = "Materialize accepted guest candidates into Person and Appearance rows."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--prompt-version", default="guest-extraction-v5")
        parser.add_argument("--first-pass-model", default="gpt-5-nano")
        parser.add_argument("--second-pass-model", default="gpt-5-mini")
        parser.add_argument("--min-confidence", type=float, default=0.90)
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete existing LLM guest appearances before syncing.",
        )

    def handle(self, *args: object, **options: object) -> None:
        if options["clear"]:
            deleted, _ = Appearance.objects.filter(
                role=Appearance.Role.GUEST,
                source="llm-guest-extraction",
            ).delete()
            self.stdout.write(f"Deleted {deleted} existing LLM guest appearance rows.")

        stats = sync_guest_appearances(
            prompt_version=str(options["prompt_version"]),
            first_pass_model=str(options["first_pass_model"]),
            second_pass_model=str(options["second_pass_model"]),
            min_confidence=float(options["min_confidence"]),
            limit=int(options["limit"]),
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Synced guest appearances: "
                f"{stats.episodes_seen} episodes, "
                f"{stats.candidates_seen} candidates, "
                f"{stats.people_created} people created, "
                f"{stats.appearances_created} appearances created, "
                f"{stats.appearances_updated} appearances updated."
            )
        )


def sync_guest_appearances(
    *,
    prompt_version: str,
    first_pass_model: str,
    second_pass_model: str,
    min_confidence: float,
    limit: int = 0,
) -> SyncStats:
    stats = SyncStats()
    episode_ids = (
        EpisodeGuestExtraction.objects.filter(
            prompt_version=prompt_version,
            status=EpisodeGuestExtraction.Status.SUCCEEDED,
        )
        .values_list("episode_id", flat=True)
        .distinct()
        .order_by("episode_id")
    )
    if limit:
        episode_ids = episode_ids[:limit]

    people_by_normalized = {
        person.normalized_name: person
        for person in Person.objects.only("id", "name", "normalized_name")
    }
    for episode_id in episode_ids.iterator(chunk_size=2000):
        stats.episodes_seen += 1
        extraction = preferred_extraction(
            episode_id=episode_id,
            prompt_version=prompt_version,
            first_pass_model=first_pass_model,
            second_pass_model=second_pass_model,
        )
        if extraction is None:
            continue
        candidates = GuestCandidate.objects.filter(
            extraction=extraction,
            confidence__gte=min_confidence,
        ).order_by("normalized_name", "-confidence")
        with transaction.atomic():
            for candidate in candidates:
                normalized = candidate.normalized_name or normalize_name(candidate.name)
                if not normalized:
                    continue
                person = people_by_normalized.get(normalized)
                if person is None:
                    person = Person.objects.create(
                        name=candidate.name.strip(),
                        normalized_name=normalized,
                    )
                    people_by_normalized[normalized] = person
                    stats.people_created += 1
                appearance, created = Appearance.objects.update_or_create(
                    episode_id=episode_id,
                    person=person,
                    role=Appearance.Role.GUEST,
                    defaults={
                        "source": "llm-guest-extraction",
                        "confidence": candidate.confidence,
                    },
                )
                stats.candidates_seen += 1
                if created:
                    stats.appearances_created += 1
                else:
                    stats.appearances_updated += 1
    return stats


def preferred_extraction(
    *,
    episode_id: int,
    prompt_version: str,
    first_pass_model: str,
    second_pass_model: str,
) -> EpisodeGuestExtraction | None:
    extraction = EpisodeGuestExtraction.objects.filter(
        episode_id=episode_id,
        prompt_version=prompt_version,
        model=second_pass_model,
        status=EpisodeGuestExtraction.Status.SUCCEEDED,
    ).first()
    if extraction is not None:
        return extraction
    return EpisodeGuestExtraction.objects.filter(
        episode_id=episode_id,
        prompt_version=prompt_version,
        model=first_pass_model,
        status=EpisodeGuestExtraction.Status.SUCCEEDED,
    ).first()
