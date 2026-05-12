from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from podcast_network.name_frequency import (
    shared_name_frequency_features,
    token_name_frequency_features,
)
from podcast_network.web.catalog.models import CanonicalPersonEntity, PersonObservation, Podcast

TOKEN_RE = re.compile(r"[a-z]+|\d+")
QUOTED_OR_PARENTHETICAL_RE = re.compile(
    r'"[^"]+"|“[^”]+”|‘[^’]+’|\'[^\']+\'|\([^)]*\)'
)
HEURISTIC_MODEL_NAME = "person-entity-heuristic-v1"
LEADING_GROUP_ARTICLES = {"a", "an", "the"}
GROUP_NAME_TOKENS = {
    "band",
    "boys",
    "brother",
    "brothers",
    "crew",
    "duo",
    "family",
    "girls",
    "group",
    "sister",
    "sisters",
    "sketch",
    "squad",
    "team",
    "trio",
    "twins",
}
NAME_NOISE_TOKENS = {
    "dr",
    "doctor",
    "prof",
    "professor",
    "mr",
    "mrs",
    "ms",
    "miss",
    "sir",
    "dame",
    "rev",
    "reverend",
    "pastor",
    "rabbi",
    "imam",
    "fr",
    "father",
    "sen",
    "senator",
    "rep",
    "representative",
    "gov",
    "governor",
    "president",
    "lt",
    "gen",
    "general",
    "md",
    "phd",
    "ph",
    "d",
    "jr",
    "sr",
    "ii",
    "iii",
    "iv",
    "ret",
    "retired",
}


@dataclass(frozen=True)
class EntityProfile:
    entity_id: str
    display_name: str
    normalized_name: str
    tokens: tuple[str, ...]
    alpha_tokens: tuple[str, ...]
    observation_count: int
    roles: tuple[str, ...]
    podcast_ids: frozenset[int]
    genres: frozenset[str]


def profile_for_entity(entity: CanonicalPersonEntity) -> EntityProfile:
    observations = PersonObservation.objects.filter(
        entity_link__canonical=entity,
    ).select_related("podcast")
    podcast_ids = set()
    genres = set()
    for observation in observations:
        podcast_ids.add(observation.podcast_id)
        genres.update(podcast_genres(observation.podcast))
    tokens = tokenize_name(entity.normalized_name)
    return EntityProfile(
        entity_id=entity.am_entity_id,
        display_name=entity.display_name,
        normalized_name=entity.normalized_name,
        tokens=tuple(tokens),
        alpha_tokens=tuple(token for token in tokens if not token.isdigit()),
        observation_count=entity.observation_count,
        roles=tuple(entity.roles or []),
        podcast_ids=frozenset(podcast_ids),
        genres=frozenset(genres),
    )


def tokenize_name(value: str) -> list[str]:
    return TOKEN_RE.findall(value.casefold())


def blocking_keys_for_profile(profile: EntityProfile) -> set[str]:
    tokens = list(profile.alpha_tokens)
    clean_tokens = list(cleaned_name_tokens(profile.normalized_name))
    if not tokens:
        return set()
    keys = set()
    keys.add(f"token-set:{' '.join(sorted(tokens))}")
    if len(tokens) >= 2:
        keys.add(f"first-last:{tokens[0]}:{tokens[-1]}")
        keys.add(f"first-two:{tokens[0]}:{tokens[1]}")
    if clean_tokens:
        keys.add(f"clean-token-set:{' '.join(sorted(clean_tokens))}")
    if len(clean_tokens) >= 2:
        keys.add(f"clean-first-last:{clean_tokens[0]}:{clean_tokens[-1]}")
        keys.add(f"clean-first-two:{clean_tokens[0]}:{clean_tokens[1]}")
    return keys


def person_pair_features(
    left: EntityProfile,
    right: EntityProfile,
    *,
    co_entity_ids_by_entity: dict[str, set[str]] | None = None,
) -> dict[str, float | int | bool]:
    left_tokens = set(left.alpha_tokens)
    right_tokens = set(right.alpha_tokens)
    left_clean_tokens = cleaned_name_tokens(left.normalized_name)
    right_clean_tokens = cleaned_name_tokens(right.normalized_name)
    left_nickname_stripped_tokens = nickname_stripped_name_tokens(
        left.display_name,
        fallback=left.normalized_name,
    )
    right_nickname_stripped_tokens = nickname_stripped_name_tokens(
        right.display_name,
        fallback=right.normalized_name,
    )
    left_clean_token_set = set(left_clean_tokens)
    right_clean_token_set = set(right_clean_tokens)
    left_nickname_stripped_token_set = set(left_nickname_stripped_tokens)
    right_nickname_stripped_token_set = set(right_nickname_stripped_tokens)
    shared_tokens = left_tokens & right_tokens
    union_tokens = left_tokens | right_tokens
    clean_shared_tokens = left_clean_token_set & right_clean_token_set
    clean_union_tokens = left_clean_token_set | right_clean_token_set
    left_extra_clean_tokens = tuple(
        token for token in left_clean_tokens if token not in right_clean_token_set
    )
    right_extra_clean_tokens = tuple(
        token for token in right_clean_tokens if token not in left_clean_token_set
    )
    extra_clean_tokens = left_extra_clean_tokens + right_extra_clean_tokens
    one_cleaned_name_properly_contains_other = (
        left_clean_token_set < right_clean_token_set
        or right_clean_token_set < left_clean_token_set
    )
    cleaned_first_last_swapped = (
        len(left_clean_tokens) >= 2
        and len(right_clean_tokens) >= 2
        and first_or_empty(left_clean_tokens) == last_or_empty(right_clean_tokens)
        and last_or_empty(left_clean_tokens) == first_or_empty(right_clean_tokens)
    )
    nickname_stripped_shared_tokens = (
        left_nickname_stripped_token_set & right_nickname_stripped_token_set
    )
    nickname_stripped_union_tokens = (
        left_nickname_stripped_token_set | right_nickname_stripped_token_set
    )
    shared_podcasts = left.podcast_ids & right.podcast_ids
    podcast_union = left.podcast_ids | right.podcast_ids
    shared_genres = left.genres & right.genres
    genre_union = left.genres | right.genres
    co_entity_ids_by_entity = co_entity_ids_by_entity or {}
    left_neighbors = co_entity_ids_by_entity.get(left.entity_id, set())
    right_neighbors = co_entity_ids_by_entity.get(right.entity_id, set())
    graph_distance = graph_distance_proxy(
        shared_podcasts=shared_podcasts,
        shared_neighbors=left_neighbors & right_neighbors,
    )
    left_frequency_features = token_name_frequency_features(left_clean_tokens)
    right_frequency_features = token_name_frequency_features(right_clean_tokens)
    shared_frequency_features = shared_name_frequency_features(
        left_clean_tokens,
        right_clean_tokens,
    )
    left_group_tokens = group_name_tokens(left_clean_tokens)
    right_group_tokens = group_name_tokens(right_clean_tokens)
    left_is_group_name = is_group_name(left_clean_tokens)
    right_is_group_name = is_group_name(right_clean_tokens)
    group_shared_tokens = set(left_group_tokens) & set(right_group_tokens)
    group_union_tokens = set(left_group_tokens) | set(right_group_tokens)
    return {
        "name_sequence_ratio": round(
            SequenceMatcher(None, left.normalized_name, right.normalized_name).ratio(),
            6,
        ),
        "token_jaccard": round(len(shared_tokens) / len(union_tokens), 6)
        if union_tokens
        else 0.0,
        "cleaned_name_sequence_ratio": cleaned_sequence_ratio(
            left_clean_tokens,
            right_clean_tokens,
        ),
        "cleaned_token_jaccard": round(len(clean_shared_tokens) / len(clean_union_tokens), 6)
        if clean_union_tokens
        else 0.0,
        "cleaned_token_overlap_count": len(clean_shared_tokens),
        "same_cleaned_token_set": left_clean_token_set == right_clean_token_set,
        "same_cleaned_token_order": left_clean_tokens == right_clean_tokens,
        "same_cleaned_first_token": first_or_empty(left_clean_tokens)
        == first_or_empty(right_clean_tokens),
        "same_cleaned_last_token": last_or_empty(left_clean_tokens)
        == last_or_empty(right_clean_tokens),
        "same_cleaned_first_and_last_token": (
            first_or_empty(left_clean_tokens) == first_or_empty(right_clean_tokens)
            and last_or_empty(left_clean_tokens) == last_or_empty(right_clean_tokens)
        ),
        "cleaned_first_last_swapped": cleaned_first_last_swapped,
        "nickname_stripped_name_sequence_ratio": cleaned_sequence_ratio(
            left_nickname_stripped_tokens,
            right_nickname_stripped_tokens,
        ),
        "nickname_stripped_token_jaccard": round(
            len(nickname_stripped_shared_tokens) / len(nickname_stripped_union_tokens),
            6,
        )
        if nickname_stripped_union_tokens
        else 0.0,
        "nickname_stripped_token_overlap_count": len(nickname_stripped_shared_tokens),
        "same_nickname_stripped_token_set": (
            left_nickname_stripped_token_set == right_nickname_stripped_token_set
        ),
        "one_name_has_quoted_nickname": has_quoted_or_parenthetical_name_part(
            left.display_name
        )
        or has_quoted_or_parenthetical_name_part(right.display_name),
        "token_overlap_count": len(shared_tokens),
        "extra_cleaned_token_count": len(extra_clean_tokens),
        "extra_cleaned_tokens_are_initials": bool(extra_clean_tokens)
        and all(len(token) == 1 for token in extra_clean_tokens),
        "extra_cleaned_tokens_are_short": bool(extra_clean_tokens)
        and all(len(token) <= 2 for token in extra_clean_tokens),
        "cleaned_token_containment_with_same_first_last": (
            one_cleaned_name_properly_contains_other
            and first_or_empty(left_clean_tokens) == first_or_empty(right_clean_tokens)
            and last_or_empty(left_clean_tokens) == last_or_empty(right_clean_tokens)
        ),
        "cleaned_token_containment_with_different_last": (
            one_cleaned_name_properly_contains_other
            and last_or_empty(left_clean_tokens) != last_or_empty(right_clean_tokens)
        ),
        "left_token_count": len(left_tokens),
        "right_token_count": len(right_tokens),
        "same_first_token": first_or_empty(left.alpha_tokens) == first_or_empty(right.alpha_tokens),
        "same_last_token": last_or_empty(left.alpha_tokens) == last_or_empty(right.alpha_tokens),
        "same_token_set": left_tokens == right_tokens,
        "one_name_contains_other_tokens": (
            left_tokens <= right_tokens or right_tokens <= left_tokens
        ),
        "left_observation_count": left.observation_count,
        "right_observation_count": right.observation_count,
        "left_is_group_name": left_is_group_name,
        "right_is_group_name": right_is_group_name,
        "one_group_name": left_is_group_name != right_is_group_name,
        "both_group_names": left_is_group_name and right_is_group_name,
        "group_name_token_jaccard": round(len(group_shared_tokens) / len(group_union_tokens), 6)
        if group_union_tokens
        else 0.0,
        "same_group_name_tokens": bool(group_union_tokens)
        and set(left_group_tokens) == set(right_group_tokens),
        "shared_group_designator": bool(
            set(left_group_tokens)
            & set(right_group_tokens)
            & GROUP_NAME_TOKENS
        ),
        "left_first_name_per_million": left_frequency_features["first_name_per_million"],
        "right_first_name_per_million": right_frequency_features["first_name_per_million"],
        "max_first_name_per_million": max(
            left_frequency_features["first_name_per_million"],
            right_frequency_features["first_name_per_million"],
        ),
        "left_last_name_per_million": left_frequency_features["last_name_per_million"],
        "right_last_name_per_million": right_frequency_features["last_name_per_million"],
        "max_last_name_per_million": max(
            left_frequency_features["last_name_per_million"],
            right_frequency_features["last_name_per_million"],
        ),
        "left_name_commonness_score": left_frequency_features["name_commonness_score"],
        "right_name_commonness_score": right_frequency_features["name_commonness_score"],
        "max_name_commonness_score": max(
            left_frequency_features["name_commonness_score"],
            right_frequency_features["name_commonness_score"],
        ),
        "shared_first_name_per_million": shared_frequency_features[
            "shared_first_name_per_million"
        ],
        "shared_last_name_per_million": shared_frequency_features["shared_last_name_per_million"],
        "shared_name_commonness_score": shared_frequency_features[
            "shared_name_commonness_score"
        ],
        "same_common_first_name": shared_frequency_features["same_common_first_name"],
        "same_common_last_name": shared_frequency_features["same_common_last_name"],
        "same_common_first_and_last_name": shared_frequency_features[
            "same_common_first_and_last_name"
        ],
        "shared_podcast_count": len(shared_podcasts),
        "podcast_jaccard": round(len(shared_podcasts) / len(podcast_union), 6)
        if podcast_union
        else 0.0,
        "shared_genre_count": len(shared_genres),
        "genre_jaccard": round(len(shared_genres) / len(genre_union), 6)
        if genre_union
        else 0.0,
        "both_host_somewhere": "host" in left.roles and "host" in right.roles,
        "both_guest_somewhere": "guest" in left.roles and "guest" in right.roles,
        "role_jaccard": role_jaccard(left.roles, right.roles),
        "graph_distance_proxy": graph_distance or 0,
        "has_graph_distance_proxy": graph_distance is not None,
    }


def graph_distance_proxy(
    *,
    shared_podcasts: set[int] | frozenset[int],
    shared_neighbors: set[str],
) -> int | None:
    if shared_podcasts:
        return 2
    if shared_neighbors:
        return 4
    return None


def role_jaccard(left: tuple[str, ...], right: tuple[str, ...]) -> float:
    left_roles = set(left)
    right_roles = set(right)
    union = left_roles | right_roles
    if not union:
        return 0.0
    return round(len(left_roles & right_roles) / len(union), 6)


def first_or_empty(values: tuple[str, ...]) -> str:
    return values[0] if values else ""


def last_or_empty(values: tuple[str, ...]) -> str:
    return values[-1] if values else ""


def cleaned_name_tokens(value: str) -> tuple[str, ...]:
    output = []
    for token in tokenize_name(value):
        if token.isdigit():
            continue
        if token in NAME_NOISE_TOKENS:
            continue
        output.append(token)
    return tuple(output)


def is_group_name(tokens: tuple[str, ...]) -> bool:
    return bool(set(tokens) & GROUP_NAME_TOKENS)


def group_name_tokens(tokens: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(token for token in tokens if token not in LEADING_GROUP_ARTICLES)


def nickname_stripped_name_tokens(value: str, *, fallback: str = "") -> tuple[str, ...]:
    stripped = QUOTED_OR_PARENTHETICAL_RE.sub(" ", value)
    tokens = cleaned_name_tokens(stripped)
    if tokens:
        return tokens
    return cleaned_name_tokens(fallback)


def has_quoted_or_parenthetical_name_part(value: str) -> bool:
    return bool(QUOTED_OR_PARENTHETICAL_RE.search(value))


def cleaned_sequence_ratio(left_tokens: tuple[str, ...], right_tokens: tuple[str, ...]) -> float:
    return round(SequenceMatcher(None, " ".join(left_tokens), " ".join(right_tokens)).ratio(), 6)


def podcast_genres(podcast: Podcast) -> set[str]:
    metadata = podcast.metadata or {}
    genres = set()
    legacy = metadata.get("legacy") or {}
    categories = legacy.get("categories") or []
    if isinstance(categories, list):
        genres.update(str(category).strip().casefold() for category in categories if category)
    apple = metadata.get("apple_podcasts") or {}
    chart_sources = apple.get("chart_sources") or []
    if isinstance(chart_sources, list):
        genres.update(str(source).strip().casefold() for source in chart_sources if source)
    return {genre for genre in genres if genre}


def heuristic_person_match_score(features: dict) -> tuple[float, list[str]]:
    reasons = []
    sequence_ratio = float(features.get("name_sequence_ratio") or 0)
    token_jaccard = float(features.get("token_jaccard") or 0)
    cleaned_sequence_ratio = float(features.get("cleaned_name_sequence_ratio") or sequence_ratio)
    cleaned_token_jaccard = float(features.get("cleaned_token_jaccard") or token_jaccard)
    nickname_stripped_sequence_ratio = float(
        features.get("nickname_stripped_name_sequence_ratio") or cleaned_sequence_ratio
    )
    nickname_stripped_token_jaccard = float(
        features.get("nickname_stripped_token_jaccard") or cleaned_token_jaccard
    )
    role_jaccard_value = float(features.get("role_jaccard") or 0)
    genre_jaccard_value = float(features.get("genre_jaccard") or 0)
    shared_podcast_count = int(features.get("shared_podcast_count") or 0)
    graph_distance = int(features.get("graph_distance_proxy") or 0)
    score = (
        0.22 * sequence_ratio
        + 0.28 * cleaned_sequence_ratio
        + 0.08 * token_jaccard
        + 0.22 * cleaned_token_jaccard
    )

    if features.get("same_token_set"):
        score += 0.16
        reasons.append("same token set")
    if features.get("same_cleaned_token_set") and not features.get("same_token_set"):
        score += 0.14
        reasons.append("same cleaned token set")
    if (
        features.get("one_name_has_quoted_nickname")
        and features.get("same_nickname_stripped_token_set")
        and not features.get("same_cleaned_token_set")
    ):
        score += 0.22
        reasons.append("same name after stripping quoted nickname")
    if features.get("one_name_contains_other_tokens"):
        score += 0.08
        reasons.append("one name contains the other's tokens")
    if nickname_stripped_token_jaccard >= 0.9 and nickname_stripped_sequence_ratio >= 0.9:
        score += 0.06
        reasons.append("high nickname-stripped similarity")
    if cleaned_token_jaccard >= 0.8 and token_jaccard < cleaned_token_jaccard:
        score += 0.05
        reasons.append("high cleaned-name similarity")
    if features.get("same_first_token") and features.get("same_last_token"):
        score += 0.08
        reasons.append("same first and last token")
    elif features.get("same_cleaned_first_token") and features.get("same_cleaned_last_token"):
        score += 0.07
        reasons.append("same cleaned first and last token")
    elif features.get("same_last_token"):
        score += 0.04
        reasons.append("same last token")

    if shared_podcast_count:
        if cleaned_token_jaccard >= 0.67:
            score += min(0.09, 0.04 + (0.015 * shared_podcast_count))
            reasons.append("shared podcast with strong name overlap")
        else:
            score += min(0.025, 0.01 + (0.005 * shared_podcast_count))
            reasons.append("shared podcast with weak name overlap")
    elif graph_distance == 4:
        score += 0.03
        reasons.append("nearby in graph")

    score += min(0.05, 0.05 * genre_jaccard_value)
    if genre_jaccard_value:
        reasons.append("similar podcast genres")
    score += min(0.03, 0.03 * role_jaccard_value)
    if role_jaccard_value:
        reasons.append("same observed role mix")

    if cleaned_token_jaccard < 0.5:
        score -= 0.18
        reasons.append("low cleaned-name overlap")
    if cleaned_token_jaccard < 0.67 and not features.get("same_cleaned_token_set"):
        score -= 0.08
        reasons.append("no strong cleaned-name match")
    if token_jaccard < 0.34 and not shared_podcast_count:
        score -= 0.10
        reasons.append("low token overlap without shared podcast")
    if not features.get("has_graph_distance_proxy") and cleaned_token_jaccard < 0.5:
        score -= 0.05
        reasons.append("no graph proximity")

    score, guard_reasons = apply_entity_score_guards(score, features)
    return round(max(0.0, min(score, 0.999)), 6), reasons + guard_reasons


def apply_entity_score_guards(score: float, features: dict) -> tuple[float, list[str]]:
    reasons = []
    if (
        features.get("both_group_names")
        and not features.get("same_group_name_tokens")
        and score > 0.2
    ):
        score = 0.2
        reasons.append("distinct group names are not person matches")
    elif features.get("one_group_name") and score > 0.3:
        score = 0.3
        reasons.append("group name compared with person name")
    return score, reasons
