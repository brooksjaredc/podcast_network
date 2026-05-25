from __future__ import annotations

from podcast_network.web.catalog.models import (
    FutureLinkPrediction,
    FutureLinkPredictionRun,
    Person,
    PersonEntityLink,
)


def latest_future_link_prediction_run() -> FutureLinkPredictionRun | None:
    return FutureLinkPredictionRun.objects.order_by("-cutoff_at", "-created_at").first()


def future_link_predictions_for_podcast(*, podcast_id: int) -> list[dict[str, object]]:
    run = latest_future_link_prediction_run()
    if run is None:
        return []
    predictions = (
        FutureLinkPrediction.objects.filter(run=run, podcast_id=podcast_id)
        .select_related("canonical")
        .order_by("rank")[:25]
    )
    rows = [future_link_guest_prediction_row(prediction) for prediction in predictions]
    attach_person_ids(rows)
    return rows


def future_link_predictions_for_person(*, person: Person) -> list[dict[str, object]]:
    run = latest_future_link_prediction_run()
    if run is None:
        return []
    canonical_ids = list(
        PersonEntityLink.objects.filter(observation__person=person)
        .values_list("canonical_id", flat=True)
        .distinct()
    )
    if not canonical_ids:
        return []
    predictions = (
        FutureLinkPrediction.objects.filter(run=run, canonical_id__in=canonical_ids)
        .select_related("podcast")
        .order_by("rank")[:25]
    )
    return [future_link_podcast_prediction_row(prediction) for prediction in predictions]


def future_link_guest_prediction_row(prediction: FutureLinkPrediction) -> dict[str, object]:
    return {
        "rank": prediction.rank,
        "score": prediction.score,
        "canonical_id": prediction.canonical_id,
        "guest_name": prediction.canonical.display_name,
        "person_id": None,
        "reason": future_link_reason(prediction.features),
    }


def future_link_podcast_prediction_row(prediction: FutureLinkPrediction) -> dict[str, object]:
    return {
        "rank": prediction.rank,
        "score": prediction.score,
        "podcast_id": prediction.podcast_id,
        "podcast_name": prediction.podcast.name,
        "reason": future_link_reason(prediction.features),
    }


def future_link_reason(features: dict[str, object]) -> str:
    parts = []
    shared_neighbor_score = numeric_feature(features, "shared_neighbor_score")
    if shared_neighbor_score:
        parts.append(f"{shared_neighbor_score:,.0f} shared-neighbor signals")
    host_bridge_count = numeric_feature(features, "host_bridge_count")
    if host_bridge_count:
        parts.append(f"{host_bridge_count:,.0f} host bridges")
    guest_appearance_count = numeric_feature(features, "guest_appearance_count")
    if guest_appearance_count:
        parts.append(f"{guest_appearance_count:,.0f} prior guest appearances")
    latest_days = numeric_feature(features, "guest_days_since_latest_appearance")
    if latest_days is not None and latest_days >= 0:
        parts.append(f"guest appeared {latest_days:,.0f} days before cutoff")
    return "; ".join(parts[:3])


def numeric_feature(features: dict[str, object], key: str) -> float | None:
    value = features.get(key)
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def attach_person_ids(rows: list[dict[str, object]]) -> None:
    canonical_ids = [str(row["canonical_id"]) for row in rows]
    person_ids_by_canonical: dict[str, int] = {}
    link_rows = (
        PersonEntityLink.objects.filter(canonical_id__in=canonical_ids)
        .values_list("canonical_id", "observation__person_id")
        .order_by("canonical_id", "observation__person_id")
        .distinct()
    )
    for canonical_id, person_id in link_rows:
        person_ids_by_canonical.setdefault(canonical_id, person_id)
    for row in rows:
        row["person_id"] = person_ids_by_canonical.get(str(row["canonical_id"]))
