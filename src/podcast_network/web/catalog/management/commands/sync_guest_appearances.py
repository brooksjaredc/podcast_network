from __future__ import annotations

from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandParser
from django.db import IntegrityError

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
    extraction_run_label: str = ""


@dataclass(frozen=True)
class GuestAppearanceCandidate:
    episode_id: int
    podcast_id: int
    display_name: str
    normalized_name: str
    confidence: float


class Command(BaseCommand):
    help = "Materialize accepted guest candidates into Person and Appearance rows."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--prompt-version", default=PROMPT_VERSION)
        parser.add_argument("--first-pass-model", default="gpt-5-nano")
        parser.add_argument("--second-pass-model", default="gpt-5-mini")
        parser.add_argument("--min-confidence", type=float, default=0.90)
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--chunk-size", type=int, default=5000)
        parser.add_argument(
            "--extraction-run-label",
            default="",
            help=(
                "Only materialize episode extractions from runs with this coordinator label. "
                "Use this for weekly incremental updates."
            ),
        )
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
            chunk_size=int(options["chunk_size"]),
            extraction_run_label=str(options["extraction_run_label"]),
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
    chunk_size: int = 5000,
    extraction_run_label: str = "",
    sync_hosts: bool = True,
    prune_single_name_people: bool = True,
) -> SyncStats:
    stats = SyncStats()
    stats.extraction_run_label = extraction_run_label
    people_by_normalized: dict[str, Person] = {}
    people_by_name = {person.name: person for person in people_by_normalized.values()}
    host_normalized_by_podcast = podcast_host_index()

    episode_extractions = EpisodeGuestExtraction.objects.filter(
        prompt_version=prompt_version,
        status=EpisodeGuestExtraction.Status.SUCCEEDED,
    )
    if extraction_run_label:
        episode_extractions = episode_extractions.filter(
            extraction_run__metadata__coordinator_label=extraction_run_label,
        )
    episode_ids = (
        episode_extractions.values_list("episode_id", flat=True).distinct().order_by("episode_id")
    )
    if limit:
        episode_ids = episode_ids[:limit]
    episode_ids = list(episode_ids)

    if sync_hosts:
        sync_host_appearances(
            people_by_normalized=people_by_normalized,
            people_by_name=people_by_name,
            host_normalized_by_podcast=host_normalized_by_podcast,
            stats=stats,
            episode_ids=episode_ids if extraction_run_label else None,
        )

    preferred_extractions = preferred_extractions_for_episodes(
        episode_ids=episode_ids,
        prompt_version=prompt_version,
        first_pass_model=first_pass_model,
        second_pass_model=second_pass_model,
    )
    stats.episodes_seen = len(episode_ids)
    extraction_ids = [extraction.id for extraction in preferred_extractions.values()]
    for extraction_id_chunk in chunks(extraction_ids, chunk_size):
        sync_guest_candidate_chunk(
            extraction_ids=extraction_id_chunk,
            host_normalized_by_podcast=host_normalized_by_podcast,
            people_by_normalized=people_by_normalized,
            people_by_name=people_by_name,
            min_confidence=min_confidence,
            stats=stats,
            chunk_size=chunk_size,
        )
    if prune_single_name_people:
        stats.single_name_people_pruned = prune_single_name_people_rows()
    return stats


def sync_guest_candidate_chunk(
    *,
    extraction_ids: list[int],
    host_normalized_by_podcast: dict[int, set[str]],
    people_by_normalized: dict[str, Person],
    people_by_name: dict[str, Person],
    min_confidence: float,
    stats: SyncStats,
    chunk_size: int,
) -> None:
    candidates = materializable_guest_candidates(
        extraction_ids=extraction_ids,
        host_normalized_by_podcast=host_normalized_by_podcast,
        min_confidence=min_confidence,
        stats=stats,
    )
    if not candidates:
        return
    sync_people_for_candidates(
        candidates=candidates,
        people_by_normalized=people_by_normalized,
        people_by_name=people_by_name,
        stats=stats,
        chunk_size=chunk_size,
    )
    bulk_upsert_guest_appearances(
        candidates=candidates,
        people_by_normalized=people_by_normalized,
        stats=stats,
        chunk_size=chunk_size,
    )


def materializable_guest_candidates(
    *,
    extraction_ids: list[int],
    host_normalized_by_podcast: dict[int, set[str]],
    min_confidence: float,
    stats: SyncStats,
) -> list[GuestAppearanceCandidate]:
    output_by_pair: dict[tuple[int, str], GuestAppearanceCandidate] = {}
    rows = (
        GuestCandidate.objects.filter(
            extraction_id__in=extraction_ids,
            confidence__gte=min_confidence,
        )
        .select_related("extraction__episode")
        .order_by("extraction__episode_id", "normalized_name", "-confidence")
    )
    for candidate in rows.iterator(chunk_size=5000):
        display_name = clean_person_display_name(candidate.name)
        normalized = normalize_name(display_name)
        if not normalized:
            continue
        if is_single_token_person_name(display_name):
            stats.skipped_single_name_candidates += 1
            continue
        episode = candidate.extraction.episode
        if normalized in host_normalized_by_podcast.get(episode.podcast_id, set()):
            stats.skipped_host_candidates += 1
            continue
        key = (episode.id, normalized)
        existing = output_by_pair.get(key)
        if existing is not None and existing.confidence >= candidate.confidence:
            continue
        output_by_pair[key] = GuestAppearanceCandidate(
            episode_id=episode.id,
            podcast_id=episode.podcast_id,
            display_name=display_name,
            normalized_name=normalized,
            confidence=candidate.confidence,
        )
    return list(output_by_pair.values())


def sync_people_for_candidates(
    *,
    candidates: list[GuestAppearanceCandidate],
    people_by_normalized: dict[str, Person],
    people_by_name: dict[str, Person],
    stats: SyncStats,
    chunk_size: int,
) -> None:
    normalized_names = {candidate.normalized_name for candidate in candidates}
    display_names = {candidate.display_name for candidate in candidates}
    load_people(
        normalized_names=normalized_names,
        display_names=display_names,
        people_by_normalized=people_by_normalized,
        people_by_name=people_by_name,
    )

    missing_by_normalized: dict[str, str] = {}
    for candidate in candidates:
        if (
            candidate.normalized_name not in people_by_normalized
            and candidate.display_name not in people_by_name
        ):
            missing_by_normalized.setdefault(candidate.normalized_name, candidate.display_name)
    if missing_by_normalized:
        people = [
            Person(name=display_name, normalized_name=normalized)
            for normalized, display_name in missing_by_normalized.items()
        ]
        try:
            created_people = Person.objects.bulk_create(people, batch_size=chunk_size)
            stats.people_created += len(created_people)
        except IntegrityError:
            for normalized, display_name in missing_by_normalized.items():
                _person, created = get_or_create_person(
                    display_name=display_name,
                    normalized=normalized,
                    people_by_normalized=people_by_normalized,
                    people_by_name=people_by_name,
                )
                if created:
                    stats.people_created += 1
        load_people(
            normalized_names=normalized_names,
            display_names=display_names,
            people_by_normalized=people_by_normalized,
            people_by_name=people_by_name,
        )

    people_to_update: dict[int, Person] = {}
    for candidate in candidates:
        person = people_by_normalized.get(candidate.normalized_name) or people_by_name.get(
            candidate.display_name
        )
        if person is None:
            continue
        people_by_normalized.setdefault(candidate.normalized_name, person)
        people_by_name.setdefault(candidate.display_name, person)
        if person.name != candidate.display_name and should_replace_display_name(
            person.name,
            candidate.display_name,
        ):
            person.name = candidate.display_name
            people_to_update[person.id] = person
    if people_to_update:
        Person.objects.bulk_update(list(people_to_update.values()), ["name"], batch_size=chunk_size)


def load_people(
    *,
    normalized_names: set[str],
    display_names: set[str],
    people_by_normalized: dict[str, Person],
    people_by_name: dict[str, Person],
) -> None:
    missing_normalized = normalized_names - set(people_by_normalized)
    missing_names = display_names - set(people_by_name)
    if not missing_normalized and not missing_names:
        return
    people = Person.objects.filter(normalized_name__in=missing_normalized)
    if missing_names:
        people = people | Person.objects.filter(name__in=missing_names)
    for person in people.only("id", "name", "normalized_name"):
        people_by_normalized.setdefault(person.normalized_name, person)
        people_by_name.setdefault(person.name, person)


def bulk_upsert_guest_appearances(
    *,
    candidates: list[GuestAppearanceCandidate],
    people_by_normalized: dict[str, Person],
    stats: SyncStats,
    chunk_size: int,
) -> None:
    rows = []
    keys = []
    for candidate in candidates:
        person = people_by_normalized.get(candidate.normalized_name)
        if person is None:
            continue
        rows.append(
            Appearance(
                episode_id=candidate.episode_id,
                person=person,
                role=Appearance.Role.GUEST,
                source="llm-guest-extraction",
                confidence=candidate.confidence,
            )
        )
        keys.append((candidate.episode_id, person.id, Appearance.Role.GUEST))
    if not rows:
        return
    existing_keys = set(
        Appearance.objects.filter(
            episode_id__in={episode_id for episode_id, _person_id, _role in keys},
            person_id__in={person_id for _episode_id, person_id, _role in keys},
            role=Appearance.Role.GUEST,
        ).values_list("episode_id", "person_id", "role")
    )
    stats.candidates_seen += len(rows)
    updated = sum(1 for key in keys if key in existing_keys)
    stats.appearances_updated += updated
    stats.appearances_created += len(keys) - updated
    Appearance.objects.bulk_create(
        rows,
        batch_size=chunk_size,
        update_conflicts=True,
        update_fields=["source", "confidence"],
        unique_fields=["episode", "person", "role"],
    )


def sync_host_appearances(
    *,
    people_by_normalized: dict[str, Person],
    people_by_name: dict[str, Person],
    host_normalized_by_podcast: dict[int, set[str]],
    stats: SyncStats,
    episode_ids: list[int] | None = None,
) -> None:
    episodes_by_podcast: dict[int, list[int]] | None = None
    podcasts = Podcast.objects.only("id")
    if episode_ids is not None:
        episodes_by_podcast = {}
        for episode_id, podcast_id in Episode.objects.filter(id__in=episode_ids).values_list(
            "id",
            "podcast_id",
        ):
            episodes_by_podcast.setdefault(podcast_id, []).append(episode_id)
        podcasts = podcasts.filter(id__in=episodes_by_podcast)
    for podcast in podcasts.iterator(chunk_size=1000):
        host_names = explicit_host_names(podcast)
        if not host_names:
            continue
        podcast_episode_ids = (
            episodes_by_podcast[podcast.id]
            if episodes_by_podcast is not None
            else list(Episode.objects.filter(podcast=podcast).values_list("id", flat=True))
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
                for episode_id in podcast_episode_ids
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

    person = (
        Person.objects.filter(normalized_name=normalized).first()
        or Person.objects.filter(name=display_name).first()
    )
    if person is not None:
        people_by_normalized.setdefault(person.normalized_name, person)
        people_by_name.setdefault(person.name, person)
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


def preferred_extractions_for_episodes(
    *,
    episode_ids: list[int],
    prompt_version: str,
    first_pass_model: str,
    second_pass_model: str,
) -> dict[int, EpisodeGuestExtraction]:
    if not episode_ids:
        return {}
    model_priority = {
        first_pass_model: 1,
        second_pass_model: 2,
    }
    rows = (
        EpisodeGuestExtraction.objects.filter(
            episode_id__in=episode_ids,
            prompt_version=prompt_version,
            model__in=model_priority,
            status=EpisodeGuestExtraction.Status.SUCCEEDED,
        )
        .select_related("episode")
        .order_by("episode_id", "model", "-created_at")
    )
    preferred: dict[int, EpisodeGuestExtraction] = {}
    for extraction in rows.iterator(chunk_size=5000):
        current = preferred.get(extraction.episode_id)
        if current is None or model_priority[extraction.model] > model_priority[current.model]:
            preferred[extraction.episode_id] = extraction
    return preferred


def chunks[T](values: list[T], chunk_size: int) -> list[list[T]]:
    chunk_size = max(chunk_size, 1)
    return [values[index : index + chunk_size] for index in range(0, len(values), chunk_size)]
