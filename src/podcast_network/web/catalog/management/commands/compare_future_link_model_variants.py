from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from django.core.management.base import BaseCommand, CommandParser
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)
from sklearn.preprocessing import StandardScaler

from podcast_network.future_link_model import (
    build_online_logistic_model,
    matrix_arrays,
    matrix_split_indexes,
    partial_fit_online_logistic,
    precision_at_k_metrics,
)


class Command(BaseCommand):
    help = "Compare one-cut future-link model variants and score calibration."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--matrix-dir", default="data/reports/future_link_full_matrix")
        parser.add_argument(
            "--output",
            default="data/reports/future_link_model_variant_comparison.json",
        )
        parser.add_argument("--batch-size", type=int, default=200000)
        parser.add_argument("--random-state", type=int, default=42)
        parser.add_argument("--max-iter", type=int, default=300)
        parser.add_argument("--positive-weight", type=float, default=1000.0)
        parser.add_argument("--alpha", type=float, default=1e-6)

    def handle(self, *args: object, **options: object) -> None:
        matrix_dir = Path(str(options["matrix_dir"]))
        metadata, x, y, split = matrix_arrays(matrix_dir)
        train_indexes = matrix_split_indexes(split, test=False)
        test_indexes = matrix_split_indexes(split, test=True)
        x_train = np.asarray(x[train_indexes], dtype=np.float32)
        y_train = np.asarray(y[train_indexes], dtype=np.uint8)
        x_test = np.asarray(x[test_indexes], dtype=np.float32)
        y_test = np.asarray(y[test_indexes], dtype=np.uint8)

        scaler = StandardScaler()
        self.stdout.write("Fitting scaler...")
        x_train_scaled = scaler.fit_transform(x_train)
        x_test_scaled = scaler.transform(x_test)

        results = []
        variants = [
            {
                "name": "exact_lr_c10_unweighted",
                "c": 10.0,
                "class_weight": None,
                "positive_weight": None,
            },
            {
                "name": "exact_lr_c10_weight1000_raw",
                "c": 10.0,
                "class_weight": {0: 1.0, 1: float(options["positive_weight"])},
                "positive_weight": float(options["positive_weight"]),
            },
        ]
        for variant in variants:
            self.stdout.write(f"Training {variant['name']}...")
            classifier = LogisticRegression(
                C=float(variant["c"]),
                class_weight=variant["class_weight"],
                max_iter=int(options["max_iter"]),
                random_state=int(options["random_state"]),
                solver="lbfgs",
            )
            classifier.fit(x_train_scaled, y_train)
            probabilities = classifier.predict_proba(x_test_scaled)[:, 1]
            results.append(
                evaluate_probabilities(
                    name=str(variant["name"]),
                    y_test=y_test,
                    probabilities=probabilities,
                )
            )
            positive_weight = variant["positive_weight"]
            if positive_weight:
                corrected = prior_correct_probabilities(
                    probabilities=probabilities,
                    positive_weight=float(positive_weight),
                )
                results.append(
                    evaluate_probabilities(
                        name=f"{variant['name']}_prior_corrected",
                        y_test=y_test,
                        probabilities=corrected,
                    )
                )

        self.stdout.write("Training online_sgd_weight1000...")
        sgd_scaler = StandardScaler()
        classifier = build_online_logistic_model(
            alpha=float(options["alpha"]),
            random_state=int(options["random_state"]),
        )
        partial_fit_online_logistic(
            classifier=classifier,
            scaler=sgd_scaler,
            x=x,
            y=y,
            train_indexes=train_indexes,
            positive_weight=float(options["positive_weight"]),
            batch_size=int(options["batch_size"]),
            classes=np.array([0, 1], dtype=np.uint8),
            scaler_is_fitted=False,
            classifier_is_fitted=False,
        )
        sgd_probabilities = score_online_batches(
            classifier=classifier,
            scaler=sgd_scaler,
            x=x,
            test_indexes=test_indexes,
            batch_size=int(options["batch_size"]),
        )
        results.append(
            evaluate_probabilities(
                name="online_sgd_weight1000_raw",
                y_test=y_test,
                probabilities=sgd_probabilities,
            )
        )
        results.append(
            evaluate_probabilities(
                name="online_sgd_weight1000_prior_corrected",
                y_test=y_test,
                probabilities=prior_correct_probabilities(
                    probabilities=sgd_probabilities,
                    positive_weight=float(options["positive_weight"]),
                ),
            )
        )

        payload: dict[str, Any] = {
            "matrix_dir": str(matrix_dir),
            "metadata": metadata,
            "train_rows": int(len(y_train)),
            "train_positive_rows": int(y_train.sum()),
            "test_rows": int(len(y_test)),
            "test_positive_rows": int(y_test.sum()),
            "variants": results,
        }
        output = Path(str(options["output"]))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        for result in results:
            self.stdout.write(json.dumps(summary_row(result), sort_keys=True))
        self.stdout.write(self.style.SUCCESS(f"Wrote comparison: {output}"))


def score_online_batches(
    *,
    classifier,
    scaler: StandardScaler,
    x: np.ndarray,
    test_indexes: np.ndarray,
    batch_size: int,
) -> np.ndarray:
    parts = []
    for start in range(0, len(test_indexes), batch_size):
        batch_indexes = test_indexes[start : start + batch_size]
        x_batch = scaler.transform(np.asarray(x[batch_indexes], dtype=np.float32))
        parts.append(classifier.predict_proba(x_batch)[:, 1])
    return np.concatenate(parts)


def evaluate_probabilities(
    *,
    name: str,
    y_test: np.ndarray,
    probabilities: np.ndarray,
) -> dict[str, Any]:
    clipped = np.clip(probabilities, 1e-15, 1 - 1e-15)
    result: dict[str, Any] = {
        "name": name,
        "average_precision": float(average_precision_score(y_test, probabilities)),
        "roc_auc": float(roc_auc_score(y_test, probabilities)),
        "brier_score": float(brier_score_loss(y_test, clipped)),
        "log_loss": float(log_loss(y_test, clipped, labels=[0, 1])),
        "score_summary": score_summary(probabilities),
        "positive_score_summary": score_summary(probabilities[y_test == 1]),
        "negative_score_summary": score_summary(probabilities[y_test == 0]),
        "histogram": histogram(probabilities),
    }
    result.update(precision_at_k_metrics(y_test=y_test, probabilities=probabilities))
    return result


def prior_correct_probabilities(*, probabilities: np.ndarray, positive_weight: float) -> np.ndarray:
    clipped = np.clip(probabilities, 1e-15, 1 - 1e-15)
    logits = np.log(clipped / (1 - clipped))
    corrected_logits = logits - math.log(positive_weight)
    return 1 / (1 + np.exp(-corrected_logits))


def score_summary(values: np.ndarray) -> dict[str, float]:
    if len(values) == 0:
        return {}
    quantiles = np.quantile(
        values,
        [0, 0.01, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99, 1.0],
    )
    keys = ["min", "p01", "p10", "p25", "p50", "p75", "p90", "p99", "max"]
    return {key: float(value) for key, value in zip(keys, quantiles, strict=True)}


def histogram(values: np.ndarray, *, bins: int = 20) -> list[dict[str, float | int]]:
    counts, edges = np.histogram(values, bins=bins, range=(0.0, 1.0))
    return [
        {
            "lower": float(edges[index]),
            "upper": float(edges[index + 1]),
            "count": int(count),
        }
        for index, count in enumerate(counts)
    ]


def summary_row(result: dict[str, Any]) -> dict[str, Any]:
    summary = result["score_summary"]
    return {
        "name": result["name"],
        "average_precision": result["average_precision"],
        "roc_auc": result["roc_auc"],
        "brier_score": result["brier_score"],
        "log_loss": result["log_loss"],
        "precision_at_100": result["precision_at_100"],
        "precision_at_1000": result["precision_at_1000"],
        "score_p50": summary.get("p50"),
        "score_p90": summary.get("p90"),
        "score_p99": summary.get("p99"),
        "score_max": summary.get("max"),
    }
