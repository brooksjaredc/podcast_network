from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations

from django.core.management.base import BaseCommand, CommandParser

from podcast_network.entity_features import (
    EntityProfile,
    blocking_keys_for_profile,
    cleaned_name_tokens,
    damerau_distance,
    person_pair_features,
    profile_for_entity,
    repeated_first_name_suffix_stripped_tokens,
)
from podcast_network.entity_resolution import person_candidate_pair_id
from podcast_network.web.catalog.models import (
    CanonicalPersonEntity,
    PersonEntityCandidatePair,
    PersonEntityLink,
)


@dataclass(frozen=True)
class CandidateGenerationStats:
    entities_seen: int = 0
    candidate_pairs: int = 0


class Command(BaseCommand):
    help = "Generate person entity candidate pairs and ML-ready features."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--limit-pairs", type=int, default=10000)
        parser.add_argument("--min-observations", type=int, default=1)
        parser.add_argument("--max-block-size", type=int, default=200)
        parser.add_argument("--chunk-size", type=int, default=5000)
        parser.add_argument("--clear", action="store_true")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args: object, **options: object) -> None:
        stats = generate_person_entity_candidates(
            limit_pairs=int(options["limit_pairs"]),
            min_observations=int(options["min_observations"]),
            max_block_size=int(options["max_block_size"]),
            chunk_size=int(options["chunk_size"]),
            clear=bool(options["clear"]),
            dry_run=bool(options["dry_run"]),
        )
        action = "Would generate" if options["dry_run"] else "Generated"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} person entity candidates: {stats.entities_seen} entities scanned, "
                f"{stats.candidate_pairs} candidate pairs."
            )
        )


def generate_person_entity_candidates(
    *,
    limit_pairs: int = 10000,
    min_observations: int = 1,
    max_block_size: int = 200,
    chunk_size: int = 5000,
    clear: bool = False,
    dry_run: bool = False,
) -> CandidateGenerationStats:
    profiles = load_profiles(min_observations=min_observations)
    pair_keys = candidate_pair_keys(
        profiles=profiles,
        max_block_size=max_block_size,
        limit_pairs=limit_pairs,
    )
    co_entity_ids_by_entity = co_entity_index(pair_keys)
    pairs = [
        candidate_pair_from_profiles(
            left=profiles[left_id],
            right=profiles[right_id],
            blocking_keys=blocking_keys_for_pair(profiles[left_id], profiles[right_id]),
            co_entity_ids_by_entity=co_entity_ids_by_entity,
        )
        for left_id, right_id in pair_keys
    ]
    if dry_run:
        return CandidateGenerationStats(entities_seen=len(profiles), candidate_pairs=len(pairs))
    if clear:
        PersonEntityCandidatePair.objects.all().delete()
    bulk_upsert_pairs(pairs, chunk_size=chunk_size)
    return CandidateGenerationStats(entities_seen=len(profiles), candidate_pairs=len(pairs))


def load_profiles(*, min_observations: int) -> dict[str, EntityProfile]:
    entities = CanonicalPersonEntity.objects.filter(
        observation_count__gte=min_observations,
    ).order_by("normalized_name")
    return {entity.am_entity_id: profile_for_entity(entity) for entity in entities}


def candidate_pair_keys(
    *,
    profiles: dict[str, EntityProfile],
    max_block_size: int,
    limit_pairs: int,
) -> list[tuple[str, str]]:
    blocks: dict[str, list[str]] = defaultdict(list)
    for entity_id, profile in profiles.items():
        for key in blocking_keys_for_profile(profile):
            blocks[key].append(entity_id)

    pair_to_keys: dict[tuple[str, str], set[str]] = defaultdict(set)
    for key, entity_ids in blocks.items():
        if len(entity_ids) < 2 or len(entity_ids) > max_block_size:
            continue
        for left_id, right_id in combinations(sorted(entity_ids), 2):
            if left_id == right_id:
                continue
            if not viable_candidate_pair(profiles[left_id], profiles[right_id]):
                continue
            left, right = sorted([left_id, right_id])
            pair_to_keys[(left, right)].add(key)

    ranked = sorted(
        pair_to_keys,
        key=lambda pair: candidate_sort_key(
            profiles[pair[0]],
            profiles[pair[1]],
            pair_to_keys[pair],
        ),
        reverse=True,
    )
    return ranked[:limit_pairs]


def candidate_sort_key(
    left: EntityProfile,
    right: EntityProfile,
    blocking_keys: set[str],
) -> tuple[int, int, int]:
    shared_tokens = set(cleaned_name_tokens(left.normalized_name)) & set(
        cleaned_name_tokens(right.normalized_name)
    )
    return (
        len(blocking_keys),
        len(shared_tokens),
        min(left.observation_count, right.observation_count),
    )


def viable_candidate_pair(left: EntityProfile, right: EntityProfile) -> bool:
    left_clean_tokens = cleaned_name_tokens(left.normalized_name)
    right_clean_tokens = cleaned_name_tokens(right.normalized_name)
    left_clean_token_set = set(left_clean_tokens)
    right_clean_token_set = set(right_clean_tokens)
    shared_clean_tokens = left_clean_token_set & right_clean_token_set
    if not left_clean_token_set or not right_clean_token_set:
        return False
    if left_clean_token_set == right_clean_token_set:
        return True
    if set(repeated_first_name_suffix_stripped_tokens(left_clean_tokens)) == set(
        repeated_first_name_suffix_stripped_tokens(right_clean_tokens)
    ):
        return True
    if (
        len(left_clean_tokens) >= 2
        and len(right_clean_tokens) >= 2
        and left_clean_tokens[0] == right_clean_tokens[0]
        and 0
        < damerau_distance(
            left_clean_tokens[-1],
            right_clean_tokens[-1],
        )
        <= 2
    ):
        return True
    return len(shared_clean_tokens) >= 2


def blocking_keys_for_pair(left: EntityProfile, right: EntityProfile) -> list[str]:
    return sorted(blocking_keys_for_profile(left) & blocking_keys_for_profile(right))


def co_entity_index(pair_keys: list[tuple[str, str]]) -> dict[str, set[str]]:
    entity_ids = {entity_id for pair in pair_keys for entity_id in pair}
    podcast_to_entities: dict[int, set[str]] = defaultdict(set)
    links = (
        PersonEntityLink.objects.filter(canonical_id__in=entity_ids)
        .select_related("observation")
        .values_list("canonical_id", "observation__podcast_id")
        .iterator(chunk_size=10000)
    )
    for entity_id, podcast_id in links:
        podcast_to_entities[podcast_id].add(entity_id)
    output: dict[str, set[str]] = defaultdict(set)
    for entity_set in podcast_to_entities.values():
        for entity_id in entity_set:
            output[entity_id].update(entity_set - {entity_id})
    return output


def candidate_pair_from_profiles(
    *,
    left: EntityProfile,
    right: EntityProfile,
    blocking_keys: list[str],
    co_entity_ids_by_entity: dict[str, set[str]],
) -> PersonEntityCandidatePair:
    left_id, right_id = sorted([left.entity_id, right.entity_id])
    ordered_left = left if left.entity_id == left_id else right
    ordered_right = right if right.entity_id == right_id else left
    return PersonEntityCandidatePair(
        pair_id=person_candidate_pair_id(left_id, right_id),
        left_id=left_id,
        right_id=right_id,
        blocking_keys=blocking_keys,
        features=person_pair_features(
            ordered_left,
            ordered_right,
            co_entity_ids_by_entity=co_entity_ids_by_entity,
        ),
        status=PersonEntityCandidatePair.Status.CANDIDATE,
    )


def bulk_upsert_pairs(pairs: list[PersonEntityCandidatePair], *, chunk_size: int) -> None:
    if not pairs:
        return
    PersonEntityCandidatePair.objects.bulk_create(
        pairs,
        batch_size=chunk_size,
        update_conflicts=True,
        unique_fields=["pair_id"],
        update_fields=[
            "left",
            "right",
            "blocking_keys",
            "features",
            "model_name",
            "match_probability",
            "status",
            "updated_at",
        ],
    )
