from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, precision_recall_fscore_support, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

FEATURE_NAMES = [
    "name_sequence_ratio",
    "token_jaccard",
    "cleaned_name_sequence_ratio",
    "cleaned_token_jaccard",
    "cleaned_token_overlap_count",
    "same_cleaned_token_set",
    "same_cleaned_token_order",
    "same_cleaned_first_token",
    "same_cleaned_last_token",
    "cleaned_last_name_damerau_similarity",
    "cleaned_full_name_damerau_similarity",
    "cleaned_last_names_within_one_edit",
    "cleaned_last_names_within_two_edits",
    "same_cleaned_first_and_last_token",
    "cleaned_first_last_swapped",
    "nickname_stripped_name_sequence_ratio",
    "nickname_stripped_token_jaccard",
    "nickname_stripped_token_overlap_count",
    "same_nickname_stripped_token_set",
    "alias_suffix_stripped_token_jaccard",
    "same_alias_suffix_stripped_token_set",
    "one_name_has_quoted_nickname",
    "token_overlap_count",
    "extra_cleaned_token_count",
    "extra_cleaned_tokens_are_initials",
    "extra_cleaned_tokens_are_short",
    "cleaned_token_containment_with_same_first_last",
    "cleaned_token_containment_with_different_last",
    "left_token_count",
    "right_token_count",
    "same_first_token",
    "same_last_token",
    "same_token_set",
    "one_name_contains_other_tokens",
    "left_observation_count",
    "right_observation_count",
    "left_is_group_name",
    "right_is_group_name",
    "one_group_name",
    "both_group_names",
    "group_name_token_jaccard",
    "same_group_name_tokens",
    "shared_group_designator",
    "left_first_name_per_million",
    "right_first_name_per_million",
    "max_first_name_per_million",
    "left_last_name_per_million",
    "right_last_name_per_million",
    "max_last_name_per_million",
    "left_name_commonness_score",
    "right_name_commonness_score",
    "max_name_commonness_score",
    "shared_first_name_per_million",
    "shared_last_name_per_million",
    "shared_name_commonness_score",
    "same_common_first_name",
    "same_common_last_name",
    "same_common_first_and_last_name",
    "shared_podcast_count",
    "podcast_jaccard",
    "shared_genre_count",
    "genre_jaccard",
    "both_host_somewhere",
    "both_guest_somewhere",
    "role_jaccard",
    "graph_distance_proxy",
    "has_graph_distance_proxy",
]


@dataclass(frozen=True)
class TrainedEntityModel:
    model_name: str
    feature_names: list[str]
    pipeline: Pipeline
    metrics: dict[str, Any]
    training_examples: int
    model_type: str = "logistic"


def feature_vector(features: dict[str, Any], feature_names: list[str] | None = None) -> list[float]:
    names = feature_names or FEATURE_NAMES
    return [feature_value(features.get(name)) for name in names]


def feature_value(value: Any) -> float:
    if isinstance(value, bool):
        return float(value)
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def train_entity_model(
    *,
    examples: list[tuple[dict[str, Any], int]],
    model_name: str,
    model_type: str = "logistic",
    random_state: int = 42,
    model_options: dict[str, Any] | None = None,
) -> TrainedEntityModel:
    if len(examples) < 10:
        raise ValueError("At least 10 labeled match/not-match examples are required.")
    labels = [label for _, label in examples]
    if len(set(labels)) < 2:
        raise ValueError("Training requires at least one match and one not-match label.")

    x = np.array([feature_vector(features) for features, _ in examples], dtype=float)
    y = np.array(labels, dtype=int)
    pipeline = build_pipeline(
        model_type=model_type,
        random_state=random_state,
        model_options=model_options,
    )
    metrics: dict[str, Any] = {}
    if min(np.bincount(y)) >= 5:
        x_train, x_test, y_train, y_test = train_test_split(
            x,
            y,
            test_size=0.25,
            random_state=random_state,
            stratify=y,
        )
        pipeline.fit(x_train, y_train)
        probabilities = pipeline.predict_proba(x_test)[:, 1]
        predictions = (probabilities >= 0.5).astype(int)
        precision, recall, f1, _ = precision_recall_fscore_support(
            y_test,
            predictions,
            average="binary",
            zero_division=0,
        )
        metrics = {
            "holdout_examples": int(len(y_test)),
            "accuracy": float(accuracy_score(y_test, predictions)),
            "precision": float(precision),
            "recall": float(recall),
            "f1": float(f1),
            "roc_auc": float(roc_auc_score(y_test, probabilities)),
        }

    pipeline.fit(x, y)
    return TrainedEntityModel(
        model_name=model_name,
        feature_names=list(FEATURE_NAMES),
        pipeline=pipeline,
        metrics=metrics,
        training_examples=len(examples),
        model_type=model_type,
    )


def train_logistic_entity_model(
    *,
    examples: list[tuple[dict[str, Any], int]],
    model_name: str,
    random_state: int = 42,
) -> TrainedEntityModel:
    return train_entity_model(
        examples=examples,
        model_name=model_name,
        model_type="logistic",
        random_state=random_state,
    )


def build_pipeline(
    *,
    model_type: str,
    random_state: int,
    model_options: dict[str, Any] | None = None,
) -> Pipeline:
    model_options = model_options or {}
    if model_type == "logistic":
        return Pipeline(
            [
                ("scaler", StandardScaler()),
                (
                    "classifier",
                    LogisticRegression(
                        class_weight="balanced",
                        max_iter=1000,
                        random_state=random_state,
                    ),
                ),
            ]
        )
    if model_type == "xgboost":
        xgb_options = {
            "n_estimators": 120,
            "max_depth": 2,
            "learning_rate": 0.05,
            "subsample": 0.9,
            "colsample_bytree": 0.9,
            "min_child_weight": 1,
            "reg_alpha": 0,
            "reg_lambda": 1.0,
            "objective": "binary:logistic",
            "eval_metric": "logloss",
            "random_state": random_state,
        }
        xgb_options.update(model_options)
        return Pipeline(
            [
                (
                    "classifier",
                    XGBClassifier(**xgb_options),
                )
            ]
        )
    raise ValueError(f"Unsupported model type: {model_type}")


def save_entity_model(model: TrainedEntityModel, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "model_name": model.model_name,
            "feature_names": model.feature_names,
            "pipeline": model.pipeline,
            "metrics": model.metrics,
            "training_examples": model.training_examples,
            "model_type": model.model_type,
        },
        path,
    )


def load_entity_model(path: Path) -> TrainedEntityModel:
    payload = joblib.load(path)
    return TrainedEntityModel(
        model_name=payload["model_name"],
        feature_names=list(payload["feature_names"]),
        pipeline=payload["pipeline"],
        metrics=dict(payload.get("metrics") or {}),
        training_examples=int(payload.get("training_examples") or 0),
        model_type=str(payload.get("model_type") or "logistic"),
    )


def predict_match_probability(model: TrainedEntityModel, features: dict[str, Any]) -> float:
    x = np.array([feature_vector(features, model.feature_names)], dtype=float)
    return float(model.pipeline.predict_proba(x)[0, 1])
