from __future__ import annotations

from django.db.models import Count, Max

from podcast_network.web.catalog.models import Appearance, Person, Podcast
from podcast_network.web.explorer.queries import (
    english_podcasts,
    guest_filter,
    is_active_podcast,
    podcast_genres,
)


def podcast_recommendations_context(
    *,
    selected_ids: list[int],
    excluded_ids: list[int],
    selected_genres: list[str],
    active_only: bool,
    sort: str,
) -> dict[str, object]:
    global_genre_options = recommendation_genre_options()
    if not selected_ids:
        return {"rows": [], "genre_options": global_genre_options}

    selected_guest_ids = list(
        Appearance.objects.filter(
            role=Appearance.Role.GUEST,
            episode__podcast_id__in=selected_ids,
        )
        .values_list("person_id", flat=True)
        .distinct()
    )
    if not selected_guest_ids:
        return {"rows": [], "genre_options": global_genre_options}

    score_rows = list(
        Appearance.objects.filter(
            role=Appearance.Role.GUEST,
            person_id__in=selected_guest_ids,
        )
        .exclude(episode__podcast_id__in=selected_ids + excluded_ids)
        .values("episode__podcast_id")
        .annotate(
            shared_guest_count=Count("person_id", distinct=True),
            matching_appearances=Count("id"),
        )
        .filter(shared_guest_count__gt=0)
        .order_by("-shared_guest_count", "-matching_appearances", "episode__podcast__name")[:200]
    )
    candidate_ids = [row["episode__podcast_id"] for row in score_rows]
    score_by_podcast_id = {row["episode__podcast_id"]: row for row in score_rows}
    recommendations_by_id = {
        podcast.id: podcast
        for podcast in Podcast.objects.filter(id__in=candidate_ids).annotate(
            unique_guests=Count(
                "episodes__appearances__person",
                filter=guest_filter("episodes__appearances"),
                distinct=True,
            ),
            latest_episode=Max("episodes__published_at"),
        )
    }
    recommendations = [
        recommendations_by_id[podcast_id]
        for podcast_id in candidate_ids
        if podcast_id in recommendations_by_id
    ]
    for podcast in recommendations:
        scores = score_by_podcast_id[podcast.id]
        podcast.shared_guest_count = scores["shared_guest_count"]
        podcast.matching_appearances = scores["matching_appearances"]
        podcast.recommendation_genres = podcast_genres(podcast)
        podcast.is_active = is_active_podcast(podcast)
        podcast.overlap_rate = recommendation_overlap_rate(podcast)
        podcast.overlap_rate_percent = round(podcast.overlap_rate * 100)
        podcast.exclusion_penalty = 0
    recommendations = english_podcasts(recommendations)
    candidate_genre_options = {
        genre for podcast in recommendations for genre in podcast.recommendation_genres
    }
    genre_options = sorted(candidate_genre_options | set(global_genre_options))
    apply_exclusion_penalties(recommendations, excluded_ids=excluded_ids)
    if selected_genres:
        recommendations = [
            podcast
            for podcast in recommendations
            if set(selected_genres) & set(podcast.recommendation_genres)
        ]
    if active_only:
        recommendations = [podcast for podcast in recommendations if podcast.is_active]
    recommendations = sorted(
        recommendations,
        key=lambda podcast: recommendation_sort_key(podcast, sort),
    )
    recommendations = recommendations[:20]
    shared_guests = shared_guests_by_podcast(
        podcast_ids=[podcast.id for podcast in recommendations],
        selected_ids=selected_ids,
        selected_guest_ids=selected_guest_ids,
    )
    explanations = recommendation_explanations(
        selected_ids=selected_ids,
        recommendation_ids=[podcast.id for podcast in recommendations],
    )
    rows = [
        {
            "podcast": podcast,
            "shared_guests": shared_guests.get(podcast.id, []),
            "explanation": explanations.get(podcast.id),
        }
        for podcast in recommendations
    ]
    return {"rows": rows, "genre_options": genre_options}


def recommendation_genre_options() -> list[str]:
    podcasts = list(
        Podcast.objects.annotate(
            guest_appearances=Count(
                "episodes__appearances",
                filter=guest_filter("episodes__appearances"),
            ),
        )
        .filter(guest_appearances__gt=0)
        .order_by("name")[:1500]
    )
    podcasts = english_podcasts(podcasts)
    return sorted({genre for podcast in podcasts for genre in podcast_genres(podcast)})


def recommendation_sort_key(podcast: Podcast, sort: str):
    if sort == "rate":
        return (
            -podcast.adjusted_overlap_rate_score,
            -podcast.overlap_rate,
            -podcast.shared_guest_count,
            -podcast.matching_appearances,
            podcast.name,
        )
    return (
        -podcast.adjusted_recommendation_score,
        -podcast.shared_guest_count,
        -podcast.matching_appearances,
        podcast.name,
    )


def apply_exclusion_penalties(podcasts: list[Podcast], *, excluded_ids: list[int]) -> None:
    for podcast in podcasts:
        podcast.adjusted_recommendation_score = recommendation_base_score(podcast)
        podcast.adjusted_overlap_rate_score = recommendation_overlap_rate_score(podcast)
        podcast.exclusion_penalty = 0
        podcast.exclusion_overlap_count = 0
        podcast.exclusion_genre_count = 0
    if not podcasts or not excluded_ids:
        return

    podcast_ids = [podcast.id for podcast in podcasts]
    excluded_guest_ids = set(
        Appearance.objects.filter(
            role=Appearance.Role.GUEST,
            episode__podcast_id__in=excluded_ids,
        )
        .values_list("person_id", flat=True)
        .distinct()
    )
    candidate_guest_rows = (
        Appearance.objects.filter(
            role=Appearance.Role.GUEST,
            episode__podcast_id__in=podcast_ids,
            person_id__in=excluded_guest_ids,
        )
        .values_list("episode__podcast_id", "person_id")
        .distinct()
    )
    guest_overlap_by_podcast: dict[int, set[int]] = {}
    for podcast_id, person_id in candidate_guest_rows:
        guest_overlap_by_podcast.setdefault(podcast_id, set()).add(person_id)

    excluded_genres = set()
    for podcast in Podcast.objects.filter(id__in=excluded_ids):
        excluded_genres.update(podcast_genres(podcast))

    for podcast in podcasts:
        guest_overlap_count = len(guest_overlap_by_podcast.get(podcast.id, set()))
        genre_overlap_count = len(set(podcast.recommendation_genres) & excluded_genres)
        penalty = guest_overlap_count * 120 + genre_overlap_count * 25
        podcast.exclusion_overlap_count = guest_overlap_count
        podcast.exclusion_genre_count = genre_overlap_count
        podcast.exclusion_penalty = penalty
        podcast.adjusted_recommendation_score = recommendation_base_score(podcast) - penalty
        podcast.adjusted_overlap_rate_score = recommendation_overlap_rate_score(podcast) - penalty


def recommendation_base_score(podcast: Podcast) -> int:
    return podcast.shared_guest_count * 100 + podcast.matching_appearances


def recommendation_overlap_rate(podcast: Podcast) -> float:
    unique_guests = podcast.unique_guests or 0
    if unique_guests == 0:
        return 0
    return podcast.shared_guest_count / unique_guests


def recommendation_overlap_rate_score(podcast: Podcast) -> int:
    return round(recommendation_overlap_rate(podcast) * 10_000) + podcast.shared_guest_count


def recommendation_explanations(
    *,
    selected_ids: list[int],
    recommendation_ids: list[int],
) -> dict[int, dict[str, object]]:
    if not selected_ids or not recommendation_ids:
        return {}

    selected_podcast_names = dict(
        Podcast.objects.filter(id__in=selected_ids).values_list("id", "name")
    )
    selected_guest_rows = (
        Appearance.objects.filter(
            role=Appearance.Role.GUEST,
            episode__podcast_id__in=selected_ids,
        )
        .values_list("episode__podcast_id", "person_id", "person__name")
        .distinct()
    )
    selected_podcasts_by_guest: dict[int, set[int]] = {}
    guest_names: dict[int, str] = {}
    for podcast_id, person_id, person_name in selected_guest_rows:
        selected_podcasts_by_guest.setdefault(person_id, set()).add(podcast_id)
        guest_names[person_id] = person_name

    overlaps: dict[int, dict[int, set[int]]] = {}
    candidate_guest_rows = (
        Appearance.objects.filter(
            role=Appearance.Role.GUEST,
            episode__podcast_id__in=recommendation_ids,
            person_id__in=selected_podcasts_by_guest.keys(),
        )
        .values_list("episode__podcast_id", "person_id")
        .distinct()
    )
    for recommendation_id, person_id in candidate_guest_rows:
        for selected_id in selected_podcasts_by_guest.get(person_id, set()):
            overlaps.setdefault(recommendation_id, {}).setdefault(selected_id, set()).add(person_id)

    appearance_counts = {
        (row["episode__podcast_id"], row["person_id"]): row["appearances_count"]
        for row in Appearance.objects.filter(
            role=Appearance.Role.GUEST,
            episode__podcast_id__in=selected_ids + recommendation_ids,
            person_id__in=selected_podcasts_by_guest.keys(),
        )
        .values("episode__podcast_id", "person_id")
        .annotate(appearances_count=Count("id"))
    }
    explanations = {}
    for recommendation_id, selected_overlaps in overlaps.items():
        selected_id, guest_ids = max(
            selected_overlaps.items(),
            key=lambda item: (len(item[1]), selected_podcast_names.get(item[0], "")),
        )
        ranked_guest_ids = sorted(
            guest_ids,
            key=lambda guest_id: (
                -(
                    appearance_counts.get((selected_id, guest_id), 0)
                    + appearance_counts.get((recommendation_id, guest_id), 0)
                ),
                -appearance_counts.get((recommendation_id, guest_id), 0),
                guest_names[guest_id],
            ),
        )
        explanations[recommendation_id] = {
            "source_podcast": selected_podcast_names.get(selected_id, ""),
            "guest_count": len(guest_ids),
            "guests": [guest_names[guest_id] for guest_id in ranked_guest_ids[:3]],
        }
    return explanations


def shared_guests_by_podcast(
    *,
    podcast_ids: list[int],
    selected_ids: list[int],
    selected_guest_ids,
) -> dict[int, list[Person]]:
    if not podcast_ids:
        return {}
    selected_counts = {
        row["person_id"]: row["appearances_count"]
        for row in Appearance.objects.filter(
            role=Appearance.Role.GUEST,
            episode__podcast_id__in=selected_ids,
            person_id__in=selected_guest_ids,
        )
        .values("person_id")
        .annotate(appearances_count=Count("id"))
    }
    rows = (
        Appearance.objects.filter(
            role=Appearance.Role.GUEST,
            episode__podcast_id__in=podcast_ids,
            person_id__in=selected_guest_ids,
        )
        .values("episode__podcast_id", "person_id", "person__name")
        .annotate(appearances_count=Count("id"))
    )
    scored_rows = sorted(
        rows,
        key=lambda row: (
            row["episode__podcast_id"],
            -(selected_counts.get(row["person_id"], 0) + row["appearances_count"]),
            -row["appearances_count"],
            row["person__name"],
        ),
    )
    guests_by_podcast: dict[int, list[Person]] = {}
    for row in scored_rows:
        podcast_id = row["episode__podcast_id"]
        person_id = row["person_id"]
        if len(guests_by_podcast.get(podcast_id, [])) >= 5:
            continue
        person = Person(id=person_id, name=row["person__name"])
        person.shared_appearance_count = (
            selected_counts.get(person_id, 0) + row["appearances_count"]
        )
        guests_by_podcast.setdefault(podcast_id, []).append(person)
    return guests_by_podcast
