from __future__ import annotations

from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction

from podcast_network.cleaning import clean_person_display_name, is_single_token_person_name
from podcast_network.extraction.pipeline import normalize_name
from podcast_network.extraction.prompt import PROMPT_VERSION
from podcast_network.web.catalog.models import (
    Appearance,
    Episode,
    EpisodeGuestExtraction,
    GuestCandidate,
    HostCandidate,
    Person,
    Podcast,
    PodcastHostExtraction,
)


@dataclass
class SyncStats:
    episodes_seen: int = 0
    candidates_seen: int = 0
    people_created: int = 0
    hosts_created: int = 0
    appearances_created: int = 0
    appearances_updated: int = 0
    host_appearances_created: int = 0
    skipped_host_candidates: int = 0
    skipped_single_name_candidates: int = 0
    single_name_people_pruned: int = 0


class Command(BaseCommand):
    help = "Materialize accepted guest candidates into Person and Appearance rows."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--prompt-version", default=PROMPT_VERSION)
        parser.add_argument("--first-pass-model", default="gpt-5-nano")
        parser.add_argument("--second-pass-model", default="gpt-5-mini")
        parser.add_argument("--min-confidence", type=float, default=0.90)
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete existing materialized LLM guest and metadata host appearances first.",
        )
        parser.add_argument(
            "--skip-host-sync",
            action="store_true",
            help="Do not create host appearances from podcast metadata.",
        )
        parser.add_argument(
            "--keep-single-name-people",
            action="store_true",
            help="Do not prune materialized people whose display name is a single token.",
        )

    def handle(self, *args: object, **options: object) -> None:
        if options["clear"]:
            deleted, _ = Appearance.objects.filter(
                source__in=["llm-guest-extraction", "podcast-metadata"],
            ).delete()
            self.stdout.write(f"Deleted {deleted} existing materialized appearance rows.")

        stats = sync_guest_appearances(
            prompt_version=str(options["prompt_version"]),
            first_pass_model=str(options["first_pass_model"]),
            second_pass_model=str(options["second_pass_model"]),
            min_confidence=float(options["min_confidence"]),
            limit=int(options["limit"]),
            sync_hosts=not bool(options["skip_host_sync"]),
            prune_single_name_people=not bool(options["keep_single_name_people"]),
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Synced guest appearances: "
                f"{stats.episodes_seen} episodes, "
                f"{stats.candidates_seen} candidates, "
                f"{stats.people_created} people created, "
                f"{stats.hosts_created} hosts created, "
                f"{stats.appearances_created} appearances created, "
                f"{stats.appearances_updated} appearances updated, "
                f"{stats.host_appearances_created} host appearances created, "
                f"{stats.skipped_host_candidates} host guest candidates skipped, "
                f"{stats.skipped_single_name_candidates} single-name candidates skipped, "
                f"{stats.single_name_people_pruned} single-name people pruned."
            )
        )


def sync_guest_appearances(
    *,
    prompt_version: str,
    first_pass_model: str,
    second_pass_model: str,
    min_confidence: float,
    limit: int = 0,
    sync_hosts: bool = True,
    prune_single_name_people: bool = True,
) -> SyncStats:
    stats = SyncStats()
    people_by_normalized = {
        person.normalized_name: person
        for person in Person.objects.only("id", "name", "normalized_name")
    }
    people_by_name = {person.name: person for person in people_by_normalized.values()}
    host_normalized_by_podcast = podcast_host_index()
    if sync_hosts:
        sync_host_appearances(
            people_by_normalized=people_by_normalized,
            people_by_name=people_by_name,
            host_normalized_by_podcast=host_normalized_by_podcast,
            stats=stats,
        )

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
        host_names = host_normalized_by_podcast.get(extraction.episode.podcast_id, set())
        candidates = GuestCandidate.objects.filter(
            extraction=extraction,
            confidence__gte=min_confidence,
        ).order_by("normalized_name", "-confidence")
        with transaction.atomic():
            for candidate in candidates:
                display_name = clean_person_display_name(candidate.name)
                normalized = normalize_name(display_name)
                if not normalized:
                    continue
                if is_single_token_person_name(display_name):
                    stats.skipped_single_name_candidates += 1
                    continue
                if normalized in host_names:
                    stats.skipped_host_candidates += 1
                    continue
                person, created = get_or_create_person(
                    display_name=display_name,
                    normalized=normalized,
                    people_by_normalized=people_by_normalized,
                    people_by_name=people_by_name,
                )
                if created:
                    stats.people_created += 1
                if person.name != display_name and should_replace_display_name(
                    person.name,
                    display_name,
                ):
                    person.name = display_name
                    person.save(update_fields=["name", "updated_at"])
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
    if prune_single_name_people:
        stats.single_name_people_pruned = prune_single_name_people_rows()
    return stats


def sync_host_appearances(
    *,
    people_by_normalized: dict[str, Person],
    people_by_name: dict[str, Person],
    host_normalized_by_podcast: dict[int, set[str]],
    stats: SyncStats,
) -> None:
    for podcast in Podcast.objects.only("id").iterator(chunk_size=1000):
        host_names = explicit_host_names(podcast)
        if not host_names:
            continue
        episode_ids = list(
            Episode.objects.filter(podcast=podcast).values_list("id", flat=True)
        )
        for host_name in host_names:
            display_name = clean_person_display_name(host_name)
            normalized = normalize_name(display_name)
            if not normalized:
                continue
            host_normalized_by_podcast.setdefault(podcast.id, set()).add(normalized)
            person, created = get_or_create_person(
                display_name=display_name,
                normalized=normalized,
                people_by_normalized=people_by_normalized,
                people_by_name=people_by_name,
            )
            if created:
                stats.hosts_created += 1
            appearances = [
                Appearance(
                    episode_id=episode_id,
                    person=person,
                    role=Appearance.Role.HOST,
                    source="podcast-metadata",
                    confidence=1.0,
                )
                for episode_id in episode_ids
            ]
            created = Appearance.objects.bulk_create(appearances, ignore_conflicts=True)
            stats.host_appearances_created += len(created)


def podcast_host_index() -> dict[int, set[str]]:
    output: dict[int, set[str]] = {}
    for podcast in Podcast.objects.only("id"):
        hosts = {
            normalize_name(clean_person_display_name(host))
            for host in explicit_host_names(podcast)
        }
        hosts.discard("")
        if hosts:
            output[podcast.id] = hosts
    return output


def explicit_host_names(podcast: Podcast) -> list[str]:
    names = []
    seen = set()
    candidates = HostCandidate.objects.filter(
        extraction__podcast=podcast,
        extraction__status=PodcastHostExtraction.Status.SUCCEEDED,
        confidence__gte=0.70,
    ).order_by("kind", "-confidence", "name")
    for candidate in candidates:
        name = candidate.name.strip()
        normalized = normalize_name(clean_person_display_name(name))
        if name and normalized and normalized not in seen:
            names.append(name)
            seen.add(normalized)
    return names


def should_replace_display_name(current: str, candidate: str) -> bool:
    if current.startswith("@") and not candidate.startswith("@"):
        return True
    return current.isupper() and not candidate.isupper()


def get_or_create_person(
    *,
    display_name: str,
    normalized: str,
    people_by_normalized: dict[str, Person],
    people_by_name: dict[str, Person],
) -> tuple[Person, bool]:
    person = people_by_normalized.get(normalized) or people_by_name.get(display_name)
    if person is not None:
        people_by_normalized.setdefault(normalized, person)
        people_by_name.setdefault(display_name, person)
        return person, False

    person = Person.objects.create(name=display_name, normalized_name=normalized)
    people_by_normalized[normalized] = person
    people_by_name[display_name] = person
    return person, True


def prune_single_name_people_rows() -> int:
    person_ids = [
        person.id
        for person in Person.objects.only("id", "name").iterator(chunk_size=5000)
        if is_single_token_person_name(person.name)
    ]
    if not person_ids:
        return 0
    people_count = len(person_ids)
    deleted, _ = Person.objects.filter(id__in=person_ids).delete()
    return people_count


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
