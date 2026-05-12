from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandParser
from django.db.models import Count, Max, Min

from podcast_network.entity_resolution import (
    canonical_person_id,
    person_observation_id,
    person_record_id,
)
from podcast_network.web.catalog.models import (
    Appearance,
    CanonicalPersonEntity,
    PersonEntityLink,
    PersonObservation,
)


@dataclass(frozen=True)
class EntitySyncStats:
    appearances_seen: int = 0
    observations_upserted: int = 0
    canonicals_upserted: int = 0
    links_upserted: int = 0


class Command(BaseCommand):
    help = "Build deterministic person-resolution observations, canonicals, and links."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--chunk-size", type=int, default=5000)
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Count rows that would be processed without writing entity-resolution tables.",
        )

    def handle(self, *args: object, **options: object) -> None:
        stats = sync_person_entities(
            limit=int(options["limit"]),
            chunk_size=int(options["chunk_size"]),
            dry_run=bool(options["dry_run"]),
        )
        action = "Would sync" if options["dry_run"] else "Synced"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} person entities: {stats.appearances_seen} appearances, "
                f"{stats.observations_upserted} observations, "
                f"{stats.canonicals_upserted} canonicals, "
                f"{stats.links_upserted} links."
            )
        )


def sync_person_entities(
    *,
    limit: int = 0,
    chunk_size: int = 5000,
    dry_run: bool = False,
) -> EntitySyncStats:
    appearances = (
        Appearance.objects.select_related("person", "episode__podcast")
        .order_by("id")
        .iterator(chunk_size=chunk_size)
    )
    observations = []
    appearances_seen = 0
    for appearance in appearances:
        appearances_seen += 1
        observations.append(observation_from_appearance(appearance))
        if limit and appearances_seen >= limit:
            break

    if dry_run:
        normalized_names = {observation.normalized_name for observation in observations}
        return EntitySyncStats(
            appearances_seen=appearances_seen,
            observations_upserted=len(observations),
            canonicals_upserted=len(normalized_names),
            links_upserted=len(observations),
        )

    bulk_upsert_observations(observations, chunk_size=chunk_size)
    canonicals = canonical_entities_for_observations(observations)
    bulk_upsert_canonicals(canonicals, chunk_size=chunk_size)
    preserved_links = existing_non_exact_links(
        observation_ids=[observation.observation_id for observation in observations],
    )
    links = []
    for observation in observations:
        preserved = preserved_links.get(observation.observation_id)
        if preserved is not None:
            links.append(preserved)
            continue
        links.append(
            PersonEntityLink(
                observation_id=observation.observation_id,
                canonical_id=canonical_person_id(observation.normalized_name),
                match_method="exact_normalized_name",
                match_probability=1.0,
            )
        )
    bulk_upsert_links(links, chunk_size=chunk_size)
    return EntitySyncStats(
        appearances_seen=appearances_seen,
        observations_upserted=len(observations),
        canonicals_upserted=len(canonicals),
        links_upserted=len(links),
    )


def existing_non_exact_links(observation_ids: list[str]) -> dict[str, PersonEntityLink]:
    if not observation_ids:
        return {}
    rows = PersonEntityLink.objects.filter(
        observation_id__in=observation_ids,
    ).exclude(match_method="exact_normalized_name")
    return {
        row.observation_id: PersonEntityLink(
            observation_id=row.observation_id,
            canonical_id=row.canonical_id,
            match_method=row.match_method,
            match_probability=row.match_probability,
        )
        for row in rows
    }


def observation_from_appearance(appearance: Appearance) -> PersonObservation:
    normalized_name = appearance.person.normalized_name
    record_id = person_record_id(
        episode_id=appearance.episode_id,
        normalized_name=normalized_name,
    )
    observation_id = person_observation_id(
        provider=PersonObservation.Provider.APPEARANCE,
        record_id=record_id,
        role=appearance.role,
    )
    return PersonObservation(
        observation_id=observation_id,
        provider=PersonObservation.Provider.APPEARANCE,
        record_id=record_id,
        appearance=appearance,
        person=appearance.person,
        episode=appearance.episode,
        podcast=appearance.episode.podcast,
        role=appearance.role,
        observed_name=appearance.person.name,
        normalized_name=normalized_name,
        source=appearance.source,
        confidence=appearance.confidence,
        context={
            "appearance_id": appearance.id,
            "episode_id": appearance.episode_id,
            "episode_title": appearance.episode.title,
            "podcast_id": appearance.episode.podcast_id,
            "podcast_name": appearance.episode.podcast.name,
        },
    )


def canonical_entities_for_observations(
    observations: list[PersonObservation],
) -> list[CanonicalPersonEntity]:
    observed_names_by_normalized: dict[str, Counter[str]] = defaultdict(Counter)
    roles_by_normalized: dict[str, set[str]] = defaultdict(set)
    for observation in observations:
        observed_names_by_normalized[observation.normalized_name][observation.observed_name] += 1
        roles_by_normalized[observation.normalized_name].add(observation.role)

    persisted_stats = {
        row["normalized_name"]: row
        for row in PersonObservation.objects.filter(
            normalized_name__in=observed_names_by_normalized.keys()
        )
        .values("normalized_name")
        .annotate(
            observation_count=Count("observation_id"),
            first_seen_at=Min("created_at"),
            last_seen_at=Max("updated_at"),
        )
    }
    persisted_names = {
        row["normalized_name"]: row["observed_name"]
        for row in PersonObservation.objects.filter(
            normalized_name__in=observed_names_by_normalized.keys()
        )
        .values("normalized_name", "observed_name")
        .annotate(name_count=Count("observation_id"))
        .order_by("normalized_name", "-name_count", "observed_name")
    }
    canonicals = []
    for normalized_name, name_counts in observed_names_by_normalized.items():
        stats = persisted_stats.get(normalized_name) or {}
        display_name = persisted_names.get(normalized_name) or name_counts.most_common(1)[0][0]
        aliases = sorted(name_counts)
        canonicals.append(
            CanonicalPersonEntity(
                am_entity_id=canonical_person_id(normalized_name),
                display_name=display_name,
                normalized_name=normalized_name,
                aliases=aliases,
                roles=sorted(roles_by_normalized[normalized_name]),
                observation_count=stats.get("observation_count") or sum(name_counts.values()),
                first_seen_at=stats.get("first_seen_at"),
                last_seen_at=stats.get("last_seen_at"),
                resolution_method="exact_normalized_name",
            )
        )
    return canonicals


def bulk_upsert_observations(
    observations: list[PersonObservation],
    *,
    chunk_size: int,
) -> None:
    if not observations:
        return
    PersonObservation.objects.bulk_create(
        observations,
        batch_size=chunk_size,
        update_conflicts=True,
        unique_fields=["observation_id"],
        update_fields=[
            "provider",
            "record_id",
            "appearance",
            "person",
            "episode",
            "podcast",
            "role",
            "observed_name",
            "normalized_name",
            "source",
            "confidence",
            "context",
            "updated_at",
        ],
    )


def bulk_upsert_canonicals(
    canonicals: list[CanonicalPersonEntity],
    *,
    chunk_size: int,
) -> None:
    if not canonicals:
        return
    CanonicalPersonEntity.objects.bulk_create(
        canonicals,
        batch_size=chunk_size,
        update_conflicts=True,
        unique_fields=["am_entity_id"],
        update_fields=[
            "display_name",
            "normalized_name",
            "aliases",
            "roles",
            "observation_count",
            "first_seen_at",
            "last_seen_at",
            "resolution_method",
            "updated_at",
        ],
    )


def bulk_upsert_links(links: list[PersonEntityLink], *, chunk_size: int) -> None:
    if not links:
        return
    PersonEntityLink.objects.bulk_create(
        links,
        batch_size=chunk_size,
        update_conflicts=True,
        unique_fields=["observation"],
        update_fields=[
            "canonical",
            "match_method",
            "match_probability",
            "dbt_updated_at",
        ],
    )
