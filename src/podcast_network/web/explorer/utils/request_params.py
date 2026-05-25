from __future__ import annotations

from datetime import datetime


def parse_date_filter(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value[:10]).date().isoformat()
    except ValueError:
        return None


def parse_int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_int_list(values: list[str]) -> list[int]:
    parsed = []
    seen = set()
    for value in values:
        parsed_value = parse_int(value)
        if parsed_value is None or parsed_value in seen:
            continue
        seen.add(parsed_value)
        parsed.append(parsed_value)
    return parsed


def parse_string_list(values: list[str]) -> list[str]:
    parsed = []
    seen = set()
    for value in values:
        parsed_value = value.strip()
        if not parsed_value or parsed_value in seen:
            continue
        seen.add(parsed_value)
        parsed.append(parsed_value)
    return parsed
