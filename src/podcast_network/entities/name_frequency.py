from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

REFERENCE_DIR = Path("data/reference/name_frequency")
FIRST_NAMES_PATH = REFERENCE_DIR / "first_names_ssa.json"
LAST_NAMES_PATH = REFERENCE_DIR / "last_names_census_2010.json"


@lru_cache(maxsize=1)
def first_name_frequencies() -> dict[str, dict[str, float]]:
    return _load_name_payload(FIRST_NAMES_PATH)


@lru_cache(maxsize=1)
def last_name_frequencies() -> dict[str, dict[str, float]]:
    return _load_name_payload(LAST_NAMES_PATH)


def _load_name_payload(path: Path) -> dict[str, dict[str, float]]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    names = payload.get("names") or {}
    return {
        str(name).casefold(): {
            "count": float(values.get("count") or 0),
            "per_million": float(values.get("per_million") or 0),
        }
        for name, values in names.items()
        if isinstance(values, dict)
    }


def token_name_frequency_features(tokens: tuple[str, ...]) -> dict[str, float | bool]:
    first = tokens[0] if tokens else ""
    last = tokens[-1] if len(tokens) >= 2 else ""
    first_stats = first_name_frequencies().get(first, {})
    last_stats = last_name_frequencies().get(last, {})
    first_per_million = float(first_stats.get("per_million") or 0)
    last_per_million = float(last_stats.get("per_million") or 0)
    first_count = float(first_stats.get("count") or 0)
    last_count = float(last_stats.get("count") or 0)
    return {
        "first_name_per_million": first_per_million,
        "last_name_per_million": last_per_million,
        "first_name_log_count": log_count(first_count),
        "last_name_log_count": log_count(last_count),
        "name_commonness_score": name_commonness_score(
            first_per_million=first_per_million,
            last_per_million=last_per_million,
        ),
        "has_first_name_frequency": bool(first_stats),
        "has_last_name_frequency": bool(last_stats),
    }


def shared_name_frequency_features(
    left_tokens: tuple[str, ...],
    right_tokens: tuple[str, ...],
) -> dict[str, float | bool]:
    left_first = left_tokens[0] if left_tokens else ""
    right_first = right_tokens[0] if right_tokens else ""
    left_last = left_tokens[-1] if len(left_tokens) >= 2 else ""
    right_last = right_tokens[-1] if len(right_tokens) >= 2 else ""
    same_first = bool(left_first and left_first == right_first)
    same_last = bool(left_last and left_last == right_last)
    first_stats = first_name_frequencies().get(left_first, {}) if same_first else {}
    last_stats = last_name_frequencies().get(left_last, {}) if same_last else {}
    first_per_million = float(first_stats.get("per_million") or 0)
    last_per_million = float(last_stats.get("per_million") or 0)
    return {
        "shared_first_name_per_million": first_per_million,
        "shared_last_name_per_million": last_per_million,
        "shared_name_commonness_score": name_commonness_score(
            first_per_million=first_per_million,
            last_per_million=last_per_million,
        ),
        "same_common_first_name": first_per_million >= 5_000,
        "same_common_last_name": last_per_million >= 500,
        "same_common_first_and_last_name": first_per_million >= 5_000
        and last_per_million >= 500,
    }


def log_count(value: float) -> float:
    return round(math.log1p(value), 6)


def name_commonness_score(*, first_per_million: float, last_per_million: float) -> float:
    if not first_per_million or not last_per_million:
        return 0.0
    return round(math.log1p(first_per_million) * math.log1p(last_per_million), 6)


def clear_name_frequency_cache() -> None:
    first_name_frequencies.cache_clear()
    last_name_frequencies.cache_clear()
