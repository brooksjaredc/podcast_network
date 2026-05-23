from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import joblib
import networkx as nx
import numpy as np
from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction
from django.db.models import Max, Min
from django.utils import timezone

from podcast_network.cloud_artifacts import download_gcs_to_path
from podcast_network.future_link_features import (
    LOGISTIC_FORWARD_FEATURES,
    build_feature_context,
    selected_feature_values,
)
from podcast_network.future_link_prediction import LinkCandidate, build_historical_link_data
from podcast_network.web.catalog.models import (
    Appearance,
    FutureLinkWeeklyAuditLink,
    FutureLinkWeeklyAuditRun,
    PersonEntityLink,
)


class Command(BaseCommand):
    help = "Score newly published podcast/guest links using features from the prior network."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--model-path", default="")
        parser.add_argument("--gcs-model-uri", default="")
        parser.add_argument("--run-id", default="")
        parser.add_argument("--output-dir", default="data/reports/future_link_weekly_audits")
        parser.add_argument("--gcs-output-uri", default="")
        parser.add_argument("--week-end", default="")
        parser.add_argument("--window-days", type=int, default=7)
        parser.add_argument("--max-degree", type=int, default=3)
        parser.add_argument("--include-hosts", action="store_true")

    def handle(self, *args: object, **options: object) -> None:
        if not options["model_path"] and not options["gcs_model_uri"]:
            raise ValueError("Provide --model-path or --gcs-model-uri.")
        window_days = int(options["window_days"])
        if window_days < 1:
            raise ValueError("--window-days must be at least 1.")
        week_end = (
            parse_cutoff(str(options["week_end"]))
            if options["week_end"]
            else latest_link_published_at()
        )
        if week_end is None:
            raise ValueError("No linked guest episode publish dates found.")
        cutoff_at = week_end - timedelta(days=window_days)
        run_id = run_id_from_options(
            explicit_run_id=str(options["run_id"]),
            output_dir=str(options["output_dir"]),
            prefix="future-link-weekly-audit",
        )

        with TemporaryDirectory() as temp_dir:
            model_path = resolve_model_path(
                model_path=str(options["model_path"]),
                gcs_model_uri=str(options["gcs_model_uri"]),
                temp_dir=Path(temp_dir),
            )
            payload = joblib.load(model_path)
            feature_names = list(payload.get("feature_names") or LOGISTIC_FORWARD_FEATURES)
            scaler = payload["scaler"]
            classifier = payload["classifier"]

            self.stdout.write(
                "Building prior network at "
                f"{cutoff_at.isoformat()} for published links through {week_end.isoformat()}..."
            )
            historical = build_historical_link_data(cutoff_at=cutoff_at)
            context = build_feature_context(cutoff_at=cutoff_at, historical=historical)
            published_rows = weekly_new_link_rows(cutoff_at=cutoff_at, week_end=week_end)
            rows = [
                row
                for row in published_rows
                if (int(row["podcast_id"]), str(row["canonical_id"]))
                not in historical.existing_guest_links
            ]
            scored_rows = []
            distance_cache: dict[int, dict[tuple[str, int | str], int]] = {}
            for row in rows:
                pair = (int(row["podcast_id"]), str(row["canonical_id"]))
                distance = candidate_distance(
                    historical=historical,
                    podcast_id=pair[0],
                    canonical_id=pair[1],
                    max_degree=int(options["max_degree"]),
                    distance_cache=distance_cache,
                )
                was_existing = pair in historical.existing_guest_links
                was_host = pair in historical.host_links
                candidate_eligible = (
                    distance is not None
                    and pair[1] in historical.guest_canonical_ids
                    and not was_existing
                    and (bool(options["include_hosts"]) or not was_host)
                )
                score = None
                feature_values: list[float] | None = None
                if candidate_eligible:
                    candidate = LinkCandidate(
                        cutoff_at=cutoff_at,
                        horizon_end=week_end,
                        podcast_id=pair[0],
                        canonical_id=pair[1],
                        distance=distance or int(options["max_degree"]),
                        label=1,
                    )
                    feature_values = selected_feature_values(
                        candidate=candidate,
                        context=context,
                        feature_names=feature_names,
                    )
                    x = np.asarray([feature_values], dtype=np.float32)
                    score = float(classifier.predict_proba(scaler.transform(x))[0, 1])
                scored_row = {
                    **row,
                    "score": score,
                    "distance": distance,
                    "candidate_eligible": candidate_eligible,
                    "was_existing_before_cutoff": was_existing,
                    "was_host_before_cutoff": was_host,
                }
                if feature_values is not None:
                    scored_row.update(dict(zip(feature_names, feature_values, strict=True)))
                scored_rows.append(scored_row)

            scored_rows.sort(
                key=lambda row: (
                    row["score"] is None,
                    -(float(row["score"]) if row["score"] is not None else -1.0),
                    row["podcast_name"],
                    row["guest_name"],
                )
            )
            for index, row in enumerate(scored_rows, start=1):
                row["rank"] = index if row["score"] is not None else ""

            metadata = {
                "week_start": cutoff_at.isoformat(),
                "week_end": week_end.isoformat(),
                "window_days": window_days,
                "model_path": str(model_path),
                "gcs_model_uri": str(options["gcs_model_uri"] or ""),
                "model_type": payload.get("model_type"),
                "event_time_field": "observation__episode__published_at",
                "feature_names": feature_names,
                "prior_guest_link_count": len(historical.existing_guest_links),
                "prior_host_link_count": len(historical.host_links),
                "prior_podcast_count": len(historical.podcast_ids),
                "prior_guest_count": len(historical.guest_canonical_ids),
                "published_pair_count": len(published_rows),
                "repeat_pair_excluded_count": len(published_rows) - len(rows),
                "new_link_count": len(scored_rows),
                "scored_link_count": sum(row["score"] is not None for row in scored_rows),
                "candidate_eligible_count": sum(row["candidate_eligible"] for row in scored_rows),
                "max_degree": int(options["max_degree"]),
                "exclude_hosts": not bool(options["include_hosts"]),
                "score_histogram": score_histogram(scored_rows),
            }
            save_audit_run(
                run_id=run_id,
                week_start=cutoff_at,
                week_end=week_end,
                metadata=metadata,
                rows=scored_rows,
                feature_names=feature_names,
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Wrote {len(scored_rows):,} weekly links, "
                    f"{metadata['scored_link_count']:,} scored to Postgres run {run_id}"
                )
            )


def latest_link_published_at() -> datetime | None:
    latest = (
        PersonEntityLink.objects.filter(observation__role=Appearance.Role.GUEST)
        .exclude(observation__episode__published_at__isnull=True)
        .aggregate(value=Max("observation__episode__published_at"))["value"]
    )
    return latest + timedelta(microseconds=1) if latest else None


def weekly_new_link_rows(*, cutoff_at: datetime, week_end: datetime) -> list[dict[str, Any]]:
    rows = (
        PersonEntityLink.objects.filter(observation__role=Appearance.Role.GUEST)
        .exclude(observation__episode__published_at__isnull=True)
        .filter(
            observation__episode__published_at__gte=cutoff_at,
            observation__episode__published_at__lt=week_end,
        )
        .values(
            "observation__podcast_id",
            "observation__episode__podcast__name",
            "canonical_id",
            "canonical__display_name",
        )
        .annotate(
            first_episode_published_at=Min("observation__episode__published_at"),
            latest_episode_published_at=Max("observation__episode__published_at"),
        )
        .order_by("-first_episode_published_at", "observation__episode__podcast__name")
    )
    return [
        {
            "podcast_id": row["observation__podcast_id"],
            "podcast_name": row["observation__episode__podcast__name"],
            "canonical_id": row["canonical_id"],
            "guest_name": row["canonical__display_name"],
            "link_published_at": row["first_episode_published_at"],
            "first_episode_published_at": row["first_episode_published_at"],
            "latest_episode_published_at": row["latest_episode_published_at"],
        }
        for row in rows
    ]


def candidate_distance(
    *,
    historical,
    podcast_id: int,
    canonical_id: str,
    max_degree: int,
    distance_cache: dict[int, dict[tuple[str, int | str], int]],
) -> int | None:
    source = ("podcast", podcast_id)
    target = ("person", canonical_id)
    if source not in historical.graph or target not in historical.graph:
        return None
    distances = distance_cache.get(podcast_id)
    if distances is None:
        distances = nx.single_source_shortest_path_length(
            historical.graph,
            source,
            cutoff=max_degree,
        )
        distance_cache[podcast_id] = distances
    distance = distances.get(target)
    return int(distance) if distance is not None else None


def score_histogram(rows: list[dict[str, Any]], *, bin_count: int = 100) -> list[dict[str, Any]]:
    counts = [0] * bin_count
    for row in rows:
        if row["score"] is None:
            continue
        score = max(0.0, min(1.0, float(row["score"])))
        counts[min(bin_count - 1, int(score * bin_count))] += 1
    return [
        {
            "lower": index / bin_count,
            "upper": (index + 1) / bin_count,
            "count": count,
        }
        for index, count in enumerate(counts)
    ]


def save_audit_run(
    *,
    rows: list[dict[str, Any]],
    feature_names: list[str],
    run_id: str,
    week_start: datetime,
    week_end: datetime,
    metadata: dict[str, Any],
) -> None:
    with transaction.atomic():
        run, _created = FutureLinkWeeklyAuditRun.objects.update_or_create(
            run_id=run_id,
            defaults={
                "week_start": week_start,
                "week_end": week_end,
                "window_days": int(metadata["window_days"]),
                "model_path": str(metadata["model_path"]),
                "gcs_model_uri": str(metadata["gcs_model_uri"]),
                "model_type": str(metadata.get("model_type") or ""),
                "feature_names": feature_names,
                "score_histogram": metadata["score_histogram"],
                "metadata": metadata,
                "published_pair_count": int(metadata["published_pair_count"]),
                "repeat_pair_excluded_count": int(metadata["repeat_pair_excluded_count"]),
                "new_link_count": int(metadata["new_link_count"]),
                "scored_link_count": int(metadata["scored_link_count"]),
                "candidate_eligible_count": int(metadata["candidate_eligible_count"]),
                "max_degree": int(metadata["max_degree"]),
            },
        )
        run.links.all().delete()
        FutureLinkWeeklyAuditLink.objects.bulk_create(
            [
                FutureLinkWeeklyAuditLink(
                    run=run,
                    rank=int(row["rank"]) if row["rank"] else None,
                    score=float(row["score"]) if row["score"] is not None else None,
                    podcast_id=int(row["podcast_id"]),
                    canonical_id=str(row["canonical_id"]),
                    link_published_at=row["link_published_at"],
                    first_episode_published_at=row["first_episode_published_at"],
                    latest_episode_published_at=row["latest_episode_published_at"],
                    distance=int(row["distance"]) if row["distance"] is not None else None,
                    candidate_eligible=bool(row["candidate_eligible"]),
                    was_existing_before_cutoff=bool(row["was_existing_before_cutoff"]),
                    was_host_before_cutoff=bool(row["was_host_before_cutoff"]),
                    features={name: row[name] for name in feature_names if name in row},
                )
                for row in rows
            ],
            batch_size=1000,
        )


def resolve_model_path(*, model_path: str, gcs_model_uri: str, temp_dir: Path) -> Path:
    if model_path:
        return Path(model_path)
    local_path = temp_dir / "future_link_model.joblib"
    download_gcs_to_path(gcs_uri=gcs_model_uri, local_path=local_path)
    return local_path


def parse_cutoff(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def run_id_from_options(*, explicit_run_id: str, output_dir: str, prefix: str) -> str:
    if explicit_run_id:
        return explicit_run_id
    path_name = Path(output_dir).name
    if path_name and path_name not in {".", "future_link_weekly_audits"}:
        return path_name
    return f"{prefix}-{timezone.now().strftime('%Y%m%d%H%M%S')}"
