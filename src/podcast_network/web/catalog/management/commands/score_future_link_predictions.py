from __future__ import annotations

import heapq
from collections import Counter
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import joblib
import numpy as np
from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction
from django.utils import timezone

from podcast_network.cloud_artifacts import download_gcs_to_path
from podcast_network.future_link_features import (
    LOGISTIC_FORWARD_FEATURES,
    build_feature_context,
    iter_degree_limited_candidates,
    selected_feature_values,
)
from podcast_network.future_link_prediction import build_historical_link_data, podcasts_to_score
from podcast_network.web.catalog.models import (
    CanonicalPersonEntity,
    FutureLinkPrediction,
    FutureLinkPredictionRun,
    Podcast,
)


class Command(BaseCommand):
    help = "Score the current network with the trained future-link model and keep top predictions."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--model-path", default="")
        parser.add_argument("--gcs-model-uri", default="")
        parser.add_argument("--run-id", default="")
        parser.add_argument("--output-dir", default="data/reports/future_link_predictions")
        parser.add_argument("--gcs-output-uri", default="")
        parser.add_argument("--top-n", type=int, default=1000)
        parser.add_argument("--batch-size", type=int, default=200000)
        parser.add_argument("--max-degree", type=int, default=3)
        parser.add_argument("--cutoff-at", default="")
        parser.add_argument("--include-inactive-podcasts", action="store_true")
        parser.add_argument("--include-hosts", action="store_true")
        parser.add_argument("--min-podcast-guest-count", type=int, default=1)

    def handle(self, *args: object, **options: object) -> None:
        if not options["model_path"] and not options["gcs_model_uri"]:
            raise ValueError("Provide --model-path or --gcs-model-uri.")
        top_n = int(options["top_n"])
        if top_n < 1:
            raise ValueError("--top-n must be at least 1.")
        batch_size = int(options["batch_size"])
        if batch_size < 1:
            raise ValueError("--batch-size must be at least 1.")

        run_id = run_id_from_options(
            explicit_run_id=str(options["run_id"]),
            output_dir=str(options["output_dir"]),
            prefix="future-link-predictions",
        )
        cutoff_at = (
            parse_cutoff(str(options["cutoff_at"])) if options["cutoff_at"] else timezone.now()
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
                "Scoring current network at "
                f"{cutoff_at.isoformat()} with {len(feature_names)} features..."
            )

            historical = build_historical_link_data(cutoff_at=cutoff_at)
            podcast_guest_counts = Counter(
                podcast_id for podcast_id, _canonical_id in historical.existing_guest_links
            )
            podcast_ids = podcasts_to_score(
                active_only=not bool(options["include_inactive_podcasts"]),
                available_podcast_ids=historical.podcast_ids,
                podcast_guest_counts=podcast_guest_counts,
                min_guest_count=int(options["min_podcast_guest_count"]),
            )
            context = build_feature_context(cutoff_at=cutoff_at, historical=historical)

            candidate_count = 0
            heap: list[tuple[float, int, dict[str, Any]]] = []
            score_histogram = [0] * 100
            batch_features: list[list[float]] = []
            batch_candidates = []
            sequence = 0
            future_links: set[tuple[int, str]] = set()
            for candidate in iter_degree_limited_candidates(
                cutoff_at=cutoff_at,
                horizon_end=cutoff_at,
                historical=historical,
                future_links=future_links,
                podcast_ids=podcast_ids,
                max_degree=int(options["max_degree"]),
                exclude_hosts=not bool(options["include_hosts"]),
            ):
                candidate_count += 1
                values = selected_feature_values(
                    candidate=candidate,
                    context=context,
                    feature_names=feature_names,
                )
                batch_features.append(values)
                batch_candidates.append((candidate, values))
                if len(batch_features) >= batch_size:
                    sequence = score_batch(
                        classifier=classifier,
                        scaler=scaler,
                        batch_features=batch_features,
                        batch_candidates=batch_candidates,
                        feature_names=feature_names,
                        heap=heap,
                        score_histogram=score_histogram,
                        top_n=top_n,
                        sequence=sequence,
                    )
                    batch_features = []
                    batch_candidates = []
                    self.stdout.write(f"Scored {candidate_count:,} candidates...")

            if batch_features:
                sequence = score_batch(
                    classifier=classifier,
                    scaler=scaler,
                    batch_features=batch_features,
                    batch_candidates=batch_candidates,
                    feature_names=feature_names,
                    heap=heap,
                    score_histogram=score_histogram,
                    top_n=top_n,
                    sequence=sequence,
                )

            rows = sorted((item[2] for item in heap), key=lambda row: row["score"], reverse=True)
            add_display_names(rows)
            for rank, row in enumerate(rows, start=1):
                row["rank"] = rank

            metadata = {
                "cutoff_at": cutoff_at.isoformat(),
                "model_path": str(model_path),
                "gcs_model_uri": str(options["gcs_model_uri"] or ""),
                "model_type": payload.get("model_type"),
                "feature_names": feature_names,
                "candidate_count": candidate_count,
                "scored_podcast_count": len(podcast_ids),
                "historical_guest_link_count": len(historical.existing_guest_links),
                "guest_count": len(historical.guest_canonical_ids),
                "top_n": top_n,
                "rows_written": len(rows),
                "score_histogram": [
                    {
                        "lower": index / len(score_histogram),
                        "upper": (index + 1) / len(score_histogram),
                        "count": count,
                    }
                    for index, count in enumerate(score_histogram)
                ],
                "max_degree": int(options["max_degree"]),
                "active_podcasts_only": not bool(options["include_inactive_podcasts"]),
                "exclude_hosts": not bool(options["include_hosts"]),
                "min_podcast_guest_count": int(options["min_podcast_guest_count"]),
            }
            save_prediction_run(
                run_id=run_id,
                cutoff_at=cutoff_at,
                metadata=metadata,
                rows=rows,
                feature_names=feature_names,
            )

            self.stdout.write(
                self.style.SUCCESS(
                    f"Wrote {len(rows):,} predictions from {candidate_count:,} "
                    f"candidates to Postgres run {run_id}"
                )
            )


def resolve_model_path(*, model_path: str, gcs_model_uri: str, temp_dir: Path) -> Path:
    if model_path:
        return Path(model_path)
    local_path = temp_dir / "future_link_model.joblib"
    download_gcs_to_path(gcs_uri=gcs_model_uri, local_path=local_path)
    return local_path


def score_batch(
    *,
    classifier: Any,
    scaler: Any,
    batch_features: list[list[float]],
    batch_candidates: list[tuple[Any, list[float]]],
    feature_names: list[str],
    heap: list[tuple[float, int, dict[str, Any]]],
    score_histogram: list[int],
    top_n: int,
    sequence: int,
) -> int:
    x_batch = np.asarray(batch_features, dtype=np.float32)
    probabilities = classifier.predict_proba(scaler.transform(x_batch))[:, 1]
    for probability, (candidate, values) in zip(probabilities, batch_candidates, strict=True):
        score = float(probability)
        histogram_index = min(
            len(score_histogram) - 1,
            int(max(0.0, min(1.0, score)) * len(score_histogram)),
        )
        score_histogram[histogram_index] += 1
        row: dict[str, Any] = {
            "rank": 0,
            "score": score,
            "podcast_id": candidate.podcast_id,
            "podcast_name": "",
            "canonical_id": candidate.canonical_id,
            "guest_name": "",
            "distance": candidate.distance,
        }
        row.update(dict(zip(feature_names, values, strict=True)))
        item = (score, sequence, row)
        sequence += 1
        if len(heap) < top_n:
            heapq.heappush(heap, item)
        elif item > heap[0]:
            heapq.heapreplace(heap, item)
    return sequence


def add_display_names(rows: list[dict[str, Any]]) -> None:
    podcast_ids = {int(row["podcast_id"]) for row in rows}
    canonical_ids = {str(row["canonical_id"]) for row in rows}
    podcasts = Podcast.objects.in_bulk(podcast_ids)
    people = CanonicalPersonEntity.objects.in_bulk(canonical_ids)
    for row in rows:
        podcast = podcasts.get(int(row["podcast_id"]))
        person = people.get(str(row["canonical_id"]))
        row["podcast_name"] = podcast.name if podcast else ""
        row["guest_name"] = person.display_name if person else ""


def save_prediction_run(
    *,
    rows: list[dict[str, Any]],
    feature_names: list[str],
    run_id: str,
    cutoff_at: datetime,
    metadata: dict[str, Any],
) -> None:
    with transaction.atomic():
        run, _created = FutureLinkPredictionRun.objects.update_or_create(
            run_id=run_id,
            defaults={
                "cutoff_at": cutoff_at,
                "model_path": str(metadata["model_path"]),
                "gcs_model_uri": str(metadata["gcs_model_uri"]),
                "model_type": str(metadata.get("model_type") or ""),
                "feature_names": feature_names,
                "score_histogram": metadata["score_histogram"],
                "metadata": metadata,
                "candidate_count": int(metadata["candidate_count"]),
                "scored_podcast_count": int(metadata["scored_podcast_count"]),
                "rows_written": int(metadata["rows_written"]),
                "max_degree": int(metadata["max_degree"]),
            },
        )
        run.predictions.all().delete()
        FutureLinkPrediction.objects.bulk_create(
            [
                FutureLinkPrediction(
                    run=run,
                    rank=int(row["rank"]),
                    score=float(row["score"]),
                    podcast_id=int(row["podcast_id"]),
                    canonical_id=str(row["canonical_id"]),
                    distance=int(row["distance"]),
                    features={name: row[name] for name in feature_names if name in row},
                )
                for row in rows
            ],
            batch_size=1000,
        )


def parse_cutoff(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def run_id_from_options(*, explicit_run_id: str, output_dir: str, prefix: str) -> str:
    if explicit_run_id:
        return explicit_run_id
    path_name = Path(output_dir).name
    if path_name and path_name not in {".", "future_link_predictions"}:
        return path_name
    return f"{prefix}-{timezone.now().strftime('%Y%m%d%H%M%S')}"
