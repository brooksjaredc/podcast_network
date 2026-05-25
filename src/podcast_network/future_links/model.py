from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.metrics import average_precision_score, precision_recall_fscore_support, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

EXCLUDED_COLUMNS = {"cutoff_at", "podcast_id", "canonical_id", "label", "split"}


@dataclass(frozen=True)
class FutureLinkModelResult:
    model_type: str
    feature_names: list[str]
    metrics: dict[str, float | int]
    pipeline: Pipeline


@dataclass(frozen=True)
class LogisticGridResult:
    matrix_dir: Path
    feature_names: list[str]
    results: list[dict[str, float | int | str | None]]


def train_future_link_model(
    *,
    dataset_path: Path,
    model_type: str,
    forward_selection: bool = False,
    max_features: int = 12,
    random_state: int = 42,
) -> FutureLinkModelResult:
    frame = pd.read_csv(dataset_path)
    if "split" not in frame or "label" not in frame:
        raise ValueError("Dataset must include split and label columns.")
    feature_names = numeric_feature_names(frame)
    if forward_selection:
        feature_names = greedy_forward_select(
            frame=frame,
            candidate_features=feature_names,
            model_type=model_type,
            max_features=max_features,
            random_state=random_state,
        )
    pipeline = build_future_link_pipeline(model_type=model_type, random_state=random_state)
    train_frame = frame[frame["split"] == "train"]
    test_frame = frame[frame["split"] == "test"]
    if train_frame.empty or test_frame.empty:
        raise ValueError("Dataset must contain both train and test rows.")
    x_train = train_frame[feature_names].fillna(0).to_numpy(dtype=float)
    y_train = train_frame["label"].to_numpy(dtype=int)
    x_test = test_frame[feature_names].fillna(0).to_numpy(dtype=float)
    y_test = test_frame["label"].to_numpy(dtype=int)
    pipeline.fit(x_train, y_train)
    probabilities = pipeline.predict_proba(x_test)[:, 1]
    predictions = (probabilities >= 0.5).astype(int)
    precision, recall, f1, _ = precision_recall_fscore_support(
        y_test,
        predictions,
        average="binary",
        zero_division=0,
    )
    metrics: dict[str, float | int] = {
        "train_rows": int(len(train_frame)),
        "test_rows": int(len(test_frame)),
        "train_positive_rows": int(y_train.sum()),
        "test_positive_rows": int(y_test.sum()),
        "average_precision": float(average_precision_score(y_test, probabilities)),
        "roc_auc": float(roc_auc_score(y_test, probabilities)),
        "precision_at_0_5": float(precision),
        "recall_at_0_5": float(recall),
        "f1_at_0_5": float(f1),
    }
    return FutureLinkModelResult(
        model_type=model_type,
        feature_names=feature_names,
        metrics=metrics,
        pipeline=pipeline,
    )


def numeric_feature_names(frame: pd.DataFrame) -> list[str]:
    return [
        column
        for column in frame.columns
        if column not in EXCLUDED_COLUMNS and pd.api.types.is_numeric_dtype(frame[column])
    ]


def greedy_forward_select(
    *,
    frame: pd.DataFrame,
    candidate_features: list[str],
    model_type: str,
    max_features: int,
    random_state: int,
) -> list[str]:
    selected: list[str] = []
    remaining = list(candidate_features)
    best_score = -1.0
    while remaining and len(selected) < max_features:
        round_scores = []
        for feature in remaining:
            features = selected + [feature]
            score = holdout_average_precision(
                frame=frame,
                feature_names=features,
                model_type=model_type,
                random_state=random_state,
            )
            round_scores.append((score, feature))
        round_scores.sort(reverse=True)
        score, feature = round_scores[0]
        if selected and score <= best_score:
            break
        selected.append(feature)
        remaining.remove(feature)
        best_score = score
    return selected or candidate_features


def holdout_average_precision(
    *,
    frame: pd.DataFrame,
    feature_names: list[str],
    model_type: str,
    random_state: int,
) -> float:
    pipeline = build_future_link_pipeline(model_type=model_type, random_state=random_state)
    train_frame = frame[frame["split"] == "train"]
    test_frame = frame[frame["split"] == "test"]
    x_train = train_frame[feature_names].fillna(0).to_numpy(dtype=float)
    y_train = train_frame["label"].to_numpy(dtype=int)
    x_test = test_frame[feature_names].fillna(0).to_numpy(dtype=float)
    y_test = test_frame["label"].to_numpy(dtype=int)
    pipeline.fit(x_train, y_train)
    probabilities = pipeline.predict_proba(x_test)[:, 1]
    return float(average_precision_score(y_test, probabilities))


def build_future_link_pipeline(*, model_type: str, random_state: int) -> Pipeline:
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
        return Pipeline(
            [
                (
                    "classifier",
                    XGBClassifier(
                        n_estimators=150,
                        max_depth=3,
                        learning_rate=0.05,
                        subsample=0.9,
                        colsample_bytree=0.9,
                        objective="binary:logistic",
                        eval_metric="logloss",
                        random_state=random_state,
                    ),
                )
            ]
        )
    raise ValueError(f"Unsupported model type: {model_type}")


def save_future_link_model(result: FutureLinkModelResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "model_type": result.model_type,
            "feature_names": result.feature_names,
            "metrics": result.metrics,
            "pipeline": result.pipeline,
        },
        path,
    )


def write_future_link_metrics(result: FutureLinkModelResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "model_type": result.model_type,
        "feature_names": result.feature_names,
        "metrics": result.metrics,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_logistic_grid_search(
    *,
    matrix_dir: Path,
    c_values: list[float],
    class_weight_values: list[str],
    random_state: int = 42,
    max_iter: int = 300,
) -> LogisticGridResult:
    metadata = json.loads((matrix_dir / "metadata.json").read_text(encoding="utf-8"))
    feature_names = list(metadata["feature_names"])
    x = np.load(matrix_dir / "X.npy", mmap_mode="r")
    y = np.load(matrix_dir / "y.npy", mmap_mode="r")
    split = np.load(matrix_dir / "split.npy", mmap_mode="r")
    train_mask = split == 0
    test_mask = split == 1
    x_train = np.asarray(x[train_mask], dtype=np.float32)
    y_train = np.asarray(y[train_mask], dtype=np.uint8)
    x_test = np.asarray(x[test_mask], dtype=np.float32)
    y_test = np.asarray(y[test_mask], dtype=np.uint8)
    scaler = StandardScaler()
    x_train = scaler.fit_transform(x_train)
    x_test = scaler.transform(x_test)

    results: list[dict[str, float | int | str | None]] = []
    for c_value in c_values:
        for class_weight_value in class_weight_values:
            class_weight = parse_class_weight(class_weight_value)
            classifier = LogisticRegression(
                C=c_value,
                class_weight=class_weight,
                max_iter=max_iter,
                random_state=random_state,
                solver="lbfgs",
            )
            classifier.fit(x_train, y_train)
            probabilities = classifier.predict_proba(x_test)[:, 1]
            predictions = (probabilities >= 0.5).astype(int)
            precision, recall, f1, _ = precision_recall_fscore_support(
                y_test,
                predictions,
                average="binary",
                zero_division=0,
            )
            result = {
                "c": float(c_value),
                "class_weight": class_weight_value,
                "train_rows": int(len(y_train)),
                "test_rows": int(len(y_test)),
                "train_positive_rows": int(y_train.sum()),
                "test_positive_rows": int(y_test.sum()),
                "average_precision": float(average_precision_score(y_test, probabilities)),
                "roc_auc": float(roc_auc_score(y_test, probabilities)),
                "precision_at_0_5": float(precision),
                "recall_at_0_5": float(recall),
                "f1_at_0_5": float(f1),
            }
            result.update(precision_at_k_metrics(y_test=y_test, probabilities=probabilities))
            results.append(result)
    results.sort(key=lambda item: float(item["average_precision"]), reverse=True)
    return LogisticGridResult(
        matrix_dir=matrix_dir,
        feature_names=feature_names,
        results=results,
    )


def parse_class_weight(value: str) -> str | dict[int, float] | None:
    if value == "none":
        return None
    if value == "balanced":
        return "balanced"
    positive_weight = float(value)
    return {0: 1.0, 1: positive_weight}


def precision_at_k_metrics(
    *,
    y_test: np.ndarray,
    probabilities: np.ndarray,
    k_values: tuple[int, ...] = (100, 500, 1000, 5000),
) -> dict[str, float | int]:
    order = np.argsort(-probabilities)
    metrics: dict[str, float | int] = {}
    positive_total = int(y_test.sum())
    for k in k_values:
        actual_k = min(k, len(y_test))
        if actual_k == 0:
            metrics[f"precision_at_{k}"] = 0.0
            metrics[f"recall_at_{k}"] = 0.0
            continue
        hits = int(y_test[order[:actual_k]].sum())
        metrics[f"precision_at_{k}"] = hits / actual_k
        metrics[f"recall_at_{k}"] = hits / positive_total if positive_total else 0.0
    return metrics


def write_logistic_grid_result(result: LogisticGridResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "matrix_dir": str(result.matrix_dir),
        "feature_names": result.feature_names,
        "results": result.results,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def matrix_arrays(matrix_dir: Path) -> tuple[dict[str, Any], np.ndarray, np.ndarray, np.ndarray]:
    metadata = json.loads((matrix_dir / "metadata.json").read_text(encoding="utf-8"))
    x = np.load(matrix_dir / "X.npy", mmap_mode="r")
    y = np.load(matrix_dir / "y.npy", mmap_mode="r")
    split = np.load(matrix_dir / "split.npy", mmap_mode="r")
    return metadata, x, y, split


def matrix_split_indexes(split: np.ndarray, *, test: bool) -> np.ndarray:
    return np.flatnonzero(split == int(test))


def batched_indexes(indexes: np.ndarray, *, batch_size: int) -> list[np.ndarray]:
    return [indexes[start : start + batch_size] for start in range(0, len(indexes), batch_size)]


def build_online_logistic_model(*, alpha: float, random_state: int) -> SGDClassifier:
    return SGDClassifier(
        loss="log_loss",
        penalty="l2",
        alpha=alpha,
        max_iter=1,
        learning_rate="optimal",
        random_state=random_state,
        warm_start=True,
    )


def partial_fit_online_logistic(
    *,
    classifier: SGDClassifier,
    scaler: StandardScaler,
    x: np.ndarray,
    y: np.ndarray,
    train_indexes: np.ndarray,
    positive_weight: float,
    batch_size: int,
    classes: np.ndarray,
    scaler_is_fitted: bool,
    classifier_is_fitted: bool,
) -> tuple[bool, bool]:
    for batch_indexes in batched_indexes(train_indexes, batch_size=batch_size):
        scaler.partial_fit(np.asarray(x[batch_indexes], dtype=np.float32))
        scaler_is_fitted = True
    for batch_indexes in batched_indexes(train_indexes, batch_size=batch_size):
        x_batch = scaler.transform(np.asarray(x[batch_indexes], dtype=np.float32))
        y_batch = np.asarray(y[batch_indexes], dtype=np.uint8)
        sample_weight = np.where(y_batch == 1, positive_weight, 1.0)
        if classifier_is_fitted:
            classifier.partial_fit(x_batch, y_batch, sample_weight=sample_weight)
        else:
            classifier.partial_fit(
                x_batch,
                y_batch,
                classes=classes,
                sample_weight=sample_weight,
            )
            classifier_is_fitted = True
    return scaler_is_fitted, classifier_is_fitted


def evaluate_online_logistic(
    *,
    classifier: SGDClassifier,
    scaler: StandardScaler,
    x: np.ndarray,
    y: np.ndarray,
    test_indexes: np.ndarray,
    batch_size: int,
) -> dict[str, float | int]:
    y_parts = []
    probability_parts = []
    for batch_indexes in batched_indexes(test_indexes, batch_size=batch_size):
        x_batch = scaler.transform(np.asarray(x[batch_indexes], dtype=np.float32))
        probabilities = classifier.predict_proba(x_batch)[:, 1]
        y_parts.append(np.asarray(y[batch_indexes], dtype=np.uint8))
        probability_parts.append(probabilities)
    y_test = np.concatenate(y_parts)
    probabilities = np.concatenate(probability_parts)
    predictions = (probabilities >= 0.5).astype(int)
    precision, recall, f1, _ = precision_recall_fscore_support(
        y_test,
        predictions,
        average="binary",
        zero_division=0,
    )
    metrics: dict[str, float | int] = {
        "test_rows": int(len(y_test)),
        "test_positive_rows": int(y_test.sum()),
        "average_precision": float(average_precision_score(y_test, probabilities)),
        "roc_auc": float(roc_auc_score(y_test, probabilities)),
        "precision_at_0_5": float(precision),
        "recall_at_0_5": float(recall),
        "f1_at_0_5": float(f1),
    }
    metrics.update(precision_at_k_metrics(y_test=y_test, probabilities=probabilities))
    return metrics
