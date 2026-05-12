from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from django.core.management.base import BaseCommand, CommandError, CommandParser
from sklearn.metrics import accuracy_score, precision_recall_fscore_support, roc_auc_score
from sklearn.model_selection import train_test_split

from podcast_network.entity_model import (
    FEATURE_NAMES,
    build_pipeline,
    feature_vector,
    save_entity_model,
    train_entity_model,
)
from podcast_network.web.catalog.models import PersonEntityPairLabel

DEFAULT_MODEL_PATH = Path("data/models/person_entity_xgboost_v1.joblib")
DEFAULT_METRICS_PATH = Path("data/reports/person_entity_model_metrics.json")
DEFAULT_DIAGNOSTICS_PATH = Path("data/reports/person_entity_xgboost_diagnostics.md")


class Command(BaseCommand):
    help = "Train a local sklearn person entity-resolution model from human labels."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--model-name", default="person-entity-xgboost-v1")
        parser.add_argument(
            "--model-type",
            choices=["logistic", "xgboost"],
            default="xgboost",
        )
        parser.add_argument("--output", default=str(DEFAULT_MODEL_PATH))
        parser.add_argument("--metrics-output", default=str(DEFAULT_METRICS_PATH))
        parser.add_argument("--diagnostics-output", default="")
        parser.add_argument("--random-state", type=int, default=42)
        parser.add_argument("--xgb-n-estimators", type=int, default=120)
        parser.add_argument("--xgb-max-depth", type=int, default=2)
        parser.add_argument("--xgb-learning-rate", type=float, default=0.05)
        parser.add_argument("--xgb-subsample", type=float, default=0.9)
        parser.add_argument("--xgb-colsample-bytree", type=float, default=0.9)
        parser.add_argument("--xgb-min-child-weight", type=float, default=1.0)
        parser.add_argument("--xgb-reg-alpha", type=float, default=0.0)
        parser.add_argument("--xgb-reg-lambda", type=float, default=1.0)

    def handle(self, *args: object, **options: object) -> None:
        labels = labeled_labels()
        examples = examples_from_labels(labels)
        model_options = xgb_model_options(options) if options["model_type"] == "xgboost" else None
        try:
            model = train_entity_model(
                examples=examples,
                model_name=str(options["model_name"]),
                model_type=str(options["model_type"]),
                random_state=int(options["random_state"]),
                model_options=model_options,
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        output = Path(str(options["output"]))
        metrics_output = Path(str(options["metrics_output"]))
        save_entity_model(model, output)
        write_metrics(model, metrics_output)
        diagnostics_output = str(options["diagnostics_output"] or "")
        if diagnostics_output:
            write_diagnostics(
                labels=labels,
                model_type=str(options["model_type"]),
                model_options=model_options,
                random_state=int(options["random_state"]),
                path=Path(diagnostics_output),
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Trained {model.model_name} on {model.training_examples} labels. "
                f"Model: {output}. Metrics: {metrics_output}."
            )
        )
        if model.metrics:
            self.stdout.write(json.dumps(model.metrics, indent=2, sort_keys=True))


def labeled_examples() -> list[tuple[dict, int]]:
    return examples_from_labels(labeled_labels())


def labeled_labels() -> list[PersonEntityPairLabel]:
    labels = PersonEntityPairLabel.objects.filter(
        label__in=[
            PersonEntityPairLabel.Label.MATCH,
            PersonEntityPairLabel.Label.NOT_MATCH,
        ]
    ).select_related("pair__left", "pair__right").order_by("created_at", "id")
    return list(labels)


def examples_from_labels(labels: list[PersonEntityPairLabel]) -> list[tuple[dict, int]]:
    examples = []
    for label in labels:
        examples.append(
            (
                training_features(label),
                int(label.label == PersonEntityPairLabel.Label.MATCH),
            )
        )
    return examples


def xgb_model_options(options: dict[str, object]) -> dict[str, Any]:
    return {
        "n_estimators": int(options["xgb_n_estimators"]),
        "max_depth": int(options["xgb_max_depth"]),
        "learning_rate": float(options["xgb_learning_rate"]),
        "subsample": float(options["xgb_subsample"]),
        "colsample_bytree": float(options["xgb_colsample_bytree"]),
        "min_child_weight": float(options["xgb_min_child_weight"]),
        "reg_alpha": float(options["xgb_reg_alpha"]),
        "reg_lambda": float(options["xgb_reg_lambda"]),
    }


def write_metrics(model, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "model_name": model.model_name,
                "model_type": model.model_type,
                "training_examples": model.training_examples,
                "feature_names": model.feature_names,
                "metrics": model.metrics,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def write_diagnostics(
    *,
    labels: list[PersonEntityPairLabel],
    model_type: str,
    model_options: dict[str, Any] | None,
    random_state: int,
    path: Path,
) -> None:
    if len(labels) < 10:
        return
    y = np.array(
        [int(label.label == PersonEntityPairLabel.Label.MATCH) for label in labels],
        dtype=int,
    )
    if len(set(y)) < 2 or min(np.bincount(y)) < 5:
        return
    x = np.array([feature_vector(training_features(label)) for label in labels], dtype=float)
    indexes = np.arange(len(labels))
    train_indexes, test_indexes = train_test_split(
        indexes,
        test_size=0.25,
        random_state=random_state,
        stratify=y,
    )
    pipeline = build_pipeline(
        model_type=model_type,
        random_state=random_state,
        model_options=model_options,
    )
    pipeline.fit(x[train_indexes], y[train_indexes])
    probabilities = pipeline.predict_proba(x[test_indexes])[:, 1]
    predictions = (probabilities >= 0.5).astype(int)
    precision, recall, f1, _ = precision_recall_fscore_support(
        y[test_indexes],
        predictions,
        average="binary",
        zero_division=0,
    )
    mistakes = []
    for position, probability, prediction in zip(
        test_indexes,
        probabilities,
        predictions,
        strict=True,
    ):
        actual = int(y[position])
        if int(prediction) == actual:
            continue
        mistakes.append(
            {
                "label": labels[int(position)],
                "actual": actual,
                "prediction": int(prediction),
                "probability": float(probability),
            }
        )
    mistakes.sort(key=lambda item: abs(0.5 - item["probability"]), reverse=True)
    lines = [
        "# Person Entity Model Diagnostics",
        "",
        f"Model type: `{model_type}`",
        f"Holdout examples: `{len(test_indexes)}`",
        f"Accuracy: `{accuracy_score(y[test_indexes], predictions):.3f}`",
        f"Precision: `{precision:.3f}`",
        f"Recall: `{recall:.3f}`",
        f"F1: `{f1:.3f}`",
        f"ROC AUC: `{roc_auc_score(y[test_indexes], probabilities):.3f}`",
        "",
        "## Feature Importance",
        "",
        "| Feature | Importance |",
        "|---|---:|",
    ]
    for feature, importance in feature_importance(pipeline)[:20]:
        lines.append(f"| `{feature}` | {importance:.4f} |")
    lines.extend(
        [
            "",
            "## Holdout Mistakes",
            "",
            "| Probability | Predicted | Actual | Left | Right | Key Features |",
            "|---:|---|---|---|---|---|",
        ]
    )
    for mistake in mistakes[:50]:
        label = mistake["label"]
        features = training_features(label)
        left, right = label_names(label)
        lines.append(
            "| "
            f"{mistake['probability']:.3f} | "
            f"{label_name(mistake['prediction'])} | "
            f"{label_name(mistake['actual'])} | "
            f"{left} | {right} | "
            f"{key_feature_summary(features)} |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def feature_importance(pipeline) -> list[tuple[str, float]]:
    classifier = pipeline.named_steps["classifier"]
    if hasattr(classifier, "feature_importances_"):
        importances = classifier.feature_importances_
    elif hasattr(classifier, "coef_"):
        importances = np.abs(classifier.coef_[0])
    else:
        return []
    pairs = zip(FEATURE_NAMES, [float(value) for value in importances], strict=True)
    return sorted(pairs, key=lambda item: item[1], reverse=True)


def label_names(label: PersonEntityPairLabel) -> tuple[str, str]:
    if label.pair_id and label.pair:
        return label.pair.left.display_name, label.pair.right.display_name
    return label.pair_id_snapshot or "unknown", ""


def label_name(value: int) -> str:
    return "match" if value else "not_match"


def key_feature_summary(features: dict) -> str:
    names = [
        "cleaned_token_jaccard",
        "nickname_stripped_token_jaccard",
        "same_cleaned_first_token",
        "same_cleaned_last_token",
        "same_cleaned_token_set",
        "same_cleaned_token_order",
        "cleaned_first_last_swapped",
        "one_name_contains_other_tokens",
        "extra_cleaned_token_count",
        "extra_cleaned_tokens_are_initials",
        "cleaned_token_containment_with_same_first_last",
        "cleaned_token_containment_with_different_last",
        "shared_podcast_count",
        "genre_jaccard",
        "role_jaccard",
    ]
    return ", ".join(f"{name}={features.get(name)}" for name in names)


def training_features(label: PersonEntityPairLabel) -> dict:
    if label.pair_id and label.pair and label.pair.features:
        return label.pair.features
    return label.features or {}
