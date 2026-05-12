from __future__ import annotations

import hashlib


def stable_hash(*parts: object, length: int = 32) -> str:
    natural_key = "|".join(str(part) for part in parts)
    return hashlib.sha256(natural_key.encode("utf-8")).hexdigest()[:length]


def person_record_id(*, episode_id: int, normalized_name: str) -> str:
    return stable_hash("person-record", episode_id, normalized_name)


def person_observation_id(*, provider: str, record_id: str, role: str) -> str:
    return stable_hash("person-observation", provider, f"{record_id}:{role}")


def canonical_person_id(normalized_name: str) -> str:
    return "person_" + stable_hash("canonical-person", normalized_name, length=24)


def person_candidate_pair_id(left_entity_id: str, right_entity_id: str) -> str:
    left, right = sorted([left_entity_id, right_entity_id])
    return stable_hash("person-candidate-pair", left, right)
