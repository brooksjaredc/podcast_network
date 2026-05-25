from __future__ import annotations

from django.db.models import Count

from podcast_network.web.catalog.models import Appearance, PersonEntityLink


def common_guest_rows(first_podcast_id: int, second_podcast_id: int) -> list[dict]:
    if PersonEntityLink.objects.exists():
        rows = canonical_common_guest_rows(first_podcast_id, second_podcast_id)
        if rows:
            return rows
    return raw_common_guest_rows(first_podcast_id, second_podcast_id)


def canonical_common_guest_rows(first_podcast_id: int, second_podcast_id: int) -> list[dict]:
    first = canonical_guest_counts(first_podcast_id)
    second = canonical_guest_counts(second_podcast_id)
    shared_ids = first.keys() & second.keys()
    rows = [
        {
            "id": first[canonical_id]["person_id"] or second[canonical_id]["person_id"],
            "name": first[canonical_id]["name"] or second[canonical_id]["name"],
            "first_appearances": first[canonical_id]["count"],
            "second_appearances": second[canonical_id]["count"],
        }
        for canonical_id in shared_ids
        if first[canonical_id]["person_id"] or second[canonical_id]["person_id"]
    ]
    return sorted(
        rows,
        key=lambda row: (-(row["first_appearances"] + row["second_appearances"]), row["name"]),
    )[:500]


def canonical_guest_counts(podcast_id: int) -> dict[str, dict]:
    counts: dict[str, dict] = {}
    rows = (
        PersonEntityLink.objects.filter(
            observation__role=Appearance.Role.GUEST,
            observation__podcast_id=podcast_id,
        )
        .values_list(
            "canonical_id",
            "canonical__display_name",
            "observation__person_id",
        )
        .iterator(chunk_size=10_000)
    )
    for canonical_id, display_name, person_id in rows:
        counts.setdefault(
            canonical_id,
            {"name": display_name, "person_id": person_id, "count": 0},
        )
        counts[canonical_id]["count"] += 1
    return counts


def raw_common_guest_rows(first_podcast_id: int, second_podcast_id: int) -> list[dict]:
    first = raw_guest_counts(first_podcast_id)
    second = raw_guest_counts(second_podcast_id)
    rows = [
        {
            "id": person_id,
            "name": first[person_id]["name"] or second[person_id]["name"],
            "first_appearances": first[person_id]["count"],
            "second_appearances": second[person_id]["count"],
        }
        for person_id in first.keys() & second.keys()
    ]
    return sorted(
        rows,
        key=lambda row: (-(row["first_appearances"] + row["second_appearances"]), row["name"]),
    )[:500]


def raw_guest_counts(podcast_id: int) -> dict[int, dict]:
    rows = (
        Appearance.objects.filter(
            role=Appearance.Role.GUEST,
            episode__podcast_id=podcast_id,
        )
        .values("person_id", "person__name")
        .annotate(count=Count("id"))
    )
    return {row["person_id"]: {"name": row["person__name"], "count": row["count"]} for row in rows}
