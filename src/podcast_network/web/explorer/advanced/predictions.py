from __future__ import annotations

from podcast_network.web.catalog.models import (
    CanonicalPersonEntity,
    FutureLinkPrediction,
    FutureLinkPredictionRun,
    FutureLinkWeeklyAuditLink,
    FutureLinkWeeklyAuditRun,
    PersonEntityLink,
)


def advanced_prediction_context() -> dict[str, object]:
    prediction_run = latest_prediction_run()
    if prediction_run is None:
        return {
            "prediction_run": None,
            "predictions": [],
            "score_histogram": [],
            "candidate_score_histogram": [],
            "score_histogram_plot": None,
            "recent_link_rows": [],
            "recent_hit_histogram": [],
            "audit_run": None,
        }

    predictions = prediction_run["predictions"]
    enrich_prediction_links(predictions)
    audit_run = latest_weekly_audit_run()
    recent_link_rows = audit_run["rows"] if audit_run else []
    enrich_prediction_links(recent_link_rows)
    candidate_score_histogram = metadata_score_histogram_counts(
        prediction_run["metadata"].get("score_histogram")
    )
    recent_hit_histogram = metadata_score_histogram_counts(
        audit_run["metadata"].get("score_histogram") if audit_run else None
    )
    return {
        "prediction_run": prediction_run,
        "predictions": predictions,
        "score_histogram": score_histogram_counts(predictions),
        "candidate_score_histogram": candidate_score_histogram,
        "score_histogram_plot": score_histogram_plot(
            candidate_counts=candidate_score_histogram,
            hit_counts=recent_hit_histogram,
        ),
        "recent_link_rows": recent_link_rows,
        "recent_hit_histogram": recent_hit_histogram,
        "audit_run": audit_run,
    }


def latest_prediction_run() -> dict[str, object] | None:
    run = FutureLinkPredictionRun.objects.order_by("-cutoff_at", "-created_at").first()
    if run is None:
        return None
    predictions = [
        prediction_row(row)
        for row in FutureLinkPrediction.objects.filter(run=run)
        .select_related("podcast", "canonical")
        .order_by("rank")[:1000]
    ]
    metadata = {
        **run.metadata,
        "cutoff_at": run.cutoff_at.isoformat(),
        "candidate_count": run.candidate_count,
        "scored_podcast_count": run.scored_podcast_count,
        "rows_written": run.rows_written,
        "max_degree": run.max_degree,
        "score_histogram": run.score_histogram,
    }
    return {
        "run_id": run.run_id,
        "metadata": metadata,
        "cutoff_at": run.cutoff_at,
        "predictions": predictions,
        "prediction_by_pair": {
            (row["podcast_id"], row["canonical_id"]): row for row in predictions
        },
    }


def prediction_row(prediction: FutureLinkPrediction) -> dict[str, object]:
    row: dict[str, object] = {
        "rank": prediction.rank,
        "score": prediction.score,
        "podcast_id": prediction.podcast_id,
        "podcast_name": prediction.podcast.name,
        "canonical_id": prediction.canonical_id,
        "guest_name": prediction.canonical.display_name,
        "distance": prediction.distance,
    }
    row.update(prediction.features)
    return row


def enrich_prediction_links(predictions: list[dict[str, object]]) -> None:
    canonical_ids = [str(row["canonical_id"]) for row in predictions]
    people = CanonicalPersonEntity.objects.in_bulk(canonical_ids)
    person_ids_by_canonical: dict[str, int] = {}
    link_rows = (
        PersonEntityLink.objects.filter(canonical_id__in=canonical_ids)
        .values_list("canonical_id", "observation__person_id")
        .order_by("canonical_id", "observation__person_id")
        .distinct()
    )
    for canonical_id, person_id in link_rows:
        person_ids_by_canonical.setdefault(canonical_id, person_id)
    for row in predictions:
        canonical_id = str(row["canonical_id"])
        person = people.get(canonical_id)
        if not row.get("guest_name") and person:
            row["guest_name"] = person.display_name
        row["person_id"] = person_ids_by_canonical.get(canonical_id)


def latest_weekly_audit_run() -> dict[str, object] | None:
    run = FutureLinkWeeklyAuditRun.objects.order_by("-week_end", "-created_at").first()
    if run is None:
        return None
    rows = [
        audit_link_row(row)
        for row in FutureLinkWeeklyAuditLink.objects.filter(run=run)
        .select_related("podcast", "canonical")
        .order_by("rank")[:500]
    ]
    metadata = {
        **run.metadata,
        "week_start": run.week_start.isoformat(),
        "week_end": run.week_end.isoformat(),
        "window_days": run.window_days,
        "published_pair_count": run.published_pair_count,
        "repeat_pair_excluded_count": run.repeat_pair_excluded_count,
        "new_link_count": run.new_link_count,
        "scored_link_count": run.scored_link_count,
        "candidate_eligible_count": run.candidate_eligible_count,
        "max_degree": run.max_degree,
        "score_histogram": run.score_histogram,
    }
    return {
        "run_id": run.run_id,
        "metadata": metadata,
        "week_end": run.week_end,
        "rows": rows,
    }


def audit_link_row(link: FutureLinkWeeklyAuditLink) -> dict[str, object]:
    row: dict[str, object] = {
        "rank": link.rank,
        "score": link.score,
        "podcast_id": link.podcast_id,
        "podcast_name": link.podcast.name,
        "canonical_id": link.canonical_id,
        "guest_name": link.canonical.display_name,
        "candidate_eligible": link.candidate_eligible,
        "link_published_at": link.link_published_at,
        "first_episode_published_at": link.first_episode_published_at,
        "distance": link.distance,
    }
    row.update(link.features)
    return row


def score_histogram_counts(
    predictions: list[dict[str, object]],
    *,
    bin_count: int = 10,
) -> list[int]:
    counts = [0] * bin_count
    if not predictions:
        return counts
    for prediction in predictions:
        score = max(0.0, min(1.0, float(prediction["score"])))
        index = min(bin_count - 1, int(score * bin_count))
        counts[index] += 1
    return counts


def metadata_score_histogram_counts(raw_bins: object, *, bin_count: int = 10) -> list[int]:
    counts = [0] * bin_count
    if not isinstance(raw_bins, list) or not raw_bins:
        return counts
    if all(isinstance(raw_bin, int | float) for raw_bin in raw_bins):
        return rebinned_counts([max(0, int(raw_bin)) for raw_bin in raw_bins], bin_count)
    for raw_bin in raw_bins:
        if not isinstance(raw_bin, dict):
            continue
        lower = float(raw_bin.get("lower", 0.0))
        count = int(raw_bin.get("count", 0))
        index = min(bin_count - 1, max(0, int(lower * bin_count)))
        counts[index] += count
    return counts


def rebinned_counts(counts: list[int], bin_count: int) -> list[int]:
    if len(counts) == bin_count:
        return counts
    output = [0] * bin_count
    if not counts:
        return output
    for index, count in enumerate(counts):
        target_index = min(bin_count - 1, int(index / len(counts) * bin_count))
        output[target_index] += count
    return output


def score_histogram_plot(
    *,
    candidate_counts: list[int],
    hit_counts: list[int],
) -> dict[str, object] | None:
    if not any(candidate_counts) and not any(hit_counts):
        return None
    bin_count = max(len(candidate_counts), len(hit_counts))
    candidate_counts = padded_counts(candidate_counts, bin_count)
    hit_counts = padded_counts(hit_counts, bin_count)
    candidate_percent = percent_values(candidate_counts)
    hit_percent = percent_values(hit_counts)
    bin_width = 1 / bin_count
    centers = [(index + 0.5) * bin_width for index in range(bin_count)]
    candidate_hover = [
        f"Score {index / bin_count:.2f}-{(index + 1) / bin_count:.2f}<br>"
        f"All candidates: {candidate_counts[index]:,}<br>"
        f"Share: {candidate_percent[index]:.4f}%"
        for index in range(bin_count)
    ]
    hit_hover = [
        f"Score {index / bin_count:.2f}-{(index + 1) / bin_count:.2f}<br>"
        f"New weekly links: {hit_counts[index]:,}<br>"
        f"Share: {hit_percent[index]:.4f}%"
        for index in range(bin_count)
    ]
    return {
        "data": [
            {
                "type": "bar",
                "name": "All candidates",
                "x": centers,
                "y": candidate_percent,
                "width": bin_width * 0.92,
                "marker": {"color": "#0f766e"},
                "opacity": 0.58,
                "hovertext": candidate_hover,
                "hoverinfo": "text",
            },
            {
                "type": "bar",
                "name": "New weekly links",
                "x": centers,
                "y": hit_percent,
                "width": bin_width * 0.52,
                "marker": {"color": "#b45309"},
                "opacity": 0.78,
                "hovertext": hit_hover,
                "hoverinfo": "text",
            },
        ],
        "layout": {
            "title": {"text": "Prediction Score Distribution"},
            "barmode": "overlay",
            "xaxis": {"title": {"text": "Prediction score"}, "range": [0, 1]},
            "yaxis": {
                "title": {"text": "Percent of population"},
                "type": "log",
                "rangemode": "tozero",
            },
            "legend": {"orientation": "h", "y": 1.12},
            "margin": {"l": 62, "r": 32, "t": 88, "b": 58},
            "font": {"family": "system-ui, sans-serif", "color": "#1f2937"},
            "plot_bgcolor": "white",
            "paper_bgcolor": "white",
        },
        "config": {"displaylogo": False, "responsive": True},
    }


def padded_counts(counts: list[int], size: int) -> list[int]:
    return counts[:size] + [0] * max(0, size - len(counts))


def percent_values(counts: list[int]) -> list[float]:
    total = sum(counts)
    if not total:
        return [0.0 for _count in counts]
    return [count / total * 100 for count in counts]
