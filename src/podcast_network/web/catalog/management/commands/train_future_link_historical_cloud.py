from __future__ import annotations

import json
import shutil
from pathlib import Path

import joblib
import numpy as np
from django.core.management.base import BaseCommand, CommandParser
from sklearn.preprocessing import StandardScaler

from podcast_network.cloud_artifacts import upload_path_to_gcs
from podcast_network.future_link_features import (
    LOGISTIC_FORWARD_FEATURES,
    build_full_feature_matrix,
)
from podcast_network.future_link_model import (
    build_online_logistic_model,
    evaluate_online_logistic,
    matrix_arrays,
    matrix_split_indexes,
    partial_fit_online_logistic,
)
from podcast_network.future_link_training import (
    FutureLinkCutConfig,
    FutureLinkSplitConfig,
    database_cut_plans,
)


class Command(BaseCommand):
    help = "Train an online future-link model over rolling historical date cuts."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--start-cutoff", required=True)
        parser.add_argument("--through-cutoff")
        parser.add_argument("--horizon-days", type=int, default=90)
        parser.add_argument("--cut-frequency-days", type=int, default=30)
        parser.add_argument("--max-cuts", type=int)
        parser.add_argument("--max-degree", type=int, default=3)
        parser.add_argument("--split-seed", default="future-link-v1")
        parser.add_argument("--test-percent", type=int, default=20)
        parser.add_argument("--positive-weight", type=float, default=1000.0)
        parser.add_argument(
            "--alpha",
            type=float,
            default=1e-6,
            help="SGD L2 regularization strength. This is the online analogue, not sklearn C.",
        )
        parser.add_argument("--batch-size", type=int, default=200000)
        parser.add_argument("--random-state", type=int, default=42)
        parser.add_argument("--work-dir", default="/tmp/future-link-training")
        parser.add_argument("--output-dir", default="/tmp/future-link-output")
        parser.add_argument("--gcs-output-uri", default="")
        parser.add_argument("--keep-cut-matrices", action="store_true")

    def handle(self, *args: object, **options: object) -> None:
        work_dir = Path(str(options["work_dir"]))
        output_dir = Path(str(options["output_dir"]))
        work_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        cut_config = FutureLinkCutConfig(
            horizon_days=int(options["horizon_days"]),
            cut_frequency_days=int(options["cut_frequency_days"]),
            start_cutoff_at=parse_cutoff(str(options["start_cutoff"])),
            through_cutoff_at=(
                parse_cutoff(str(options["through_cutoff"]))
                if options["through_cutoff"]
                else None
            ),
            max_cuts=options["max_cuts"],
        )
        split_config = FutureLinkSplitConfig(
            seed=str(options["split_seed"]),
            test_percent=int(options["test_percent"]),
        )
        plans = database_cut_plans(
            shard_base_uri="gs://placeholder/future-link-training",
            split_config=split_config,
            cut_config=cut_config,
        )
        if not plans:
            self.stdout.write(self.style.WARNING("No date cuts planned."))
            return

        classifier = build_online_logistic_model(
            alpha=float(options["alpha"]),
            random_state=int(options["random_state"]),
        )
        scaler = StandardScaler()
        scaler_is_fitted = False
        classifier_is_fitted = False
        metrics_rows = []
        classes = np.array([0, 1], dtype=np.uint8)
        for index, plan in enumerate(plans, start=1):
            matrix_dir = work_dir / f"cutoff={plan.cutoff_at.date().isoformat()}"
            self.stdout.write(
                f"[{index}/{len(plans)}] Building matrix for cutoff {plan.cutoff_at.date()}..."
            )
            stats = build_full_feature_matrix(
                output_dir=matrix_dir,
                cutoff_at=plan.cutoff_at,
                horizon_days=int(options["horizon_days"]),
                max_degree=int(options["max_degree"]),
                feature_names=list(LOGISTIC_FORWARD_FEATURES),
                split_seed=split_config.seed,
                test_percent=split_config.test_percent,
            )
            metadata, x, y, split = matrix_arrays(matrix_dir)
            train_indexes = matrix_split_indexes(split, test=False)
            test_indexes = matrix_split_indexes(split, test=True)
            metric_row = {
                "cutoff_at": plan.cutoff_at.isoformat(),
                "horizon_start": plan.horizon_start.isoformat(),
                "horizon_end": plan.horizon_end.isoformat(),
                "row_count": stats.row_count,
                "positive_count": stats.positive_count,
                "train_rows": int(len(train_indexes)),
                "test_rows": int(len(test_indexes)),
                "feature_names": metadata["feature_names"],
            }
            if classifier_is_fitted and scaler_is_fitted and int(y[test_indexes].sum()) > 0:
                metric_row.update(
                    evaluate_online_logistic(
                        classifier=classifier,
                        scaler=scaler,
                        x=x,
                        y=y,
                        test_indexes=test_indexes,
                        batch_size=int(options["batch_size"]),
                    )
                )
            else:
                metric_row["status"] = "training_only_first_cut_or_no_test_positives"
            self.stdout.write(json.dumps(metric_row, sort_keys=True))
            metrics_rows.append(metric_row)

            scaler_is_fitted, classifier_is_fitted = partial_fit_online_logistic(
                classifier=classifier,
                scaler=scaler,
                x=x,
                y=y,
                train_indexes=train_indexes,
                positive_weight=float(options["positive_weight"]),
                batch_size=int(options["batch_size"]),
                classes=classes,
                scaler_is_fitted=scaler_is_fitted,
                classifier_is_fitted=classifier_is_fitted,
            )
            write_jsonl(output_dir / "cut_metrics.jsonl", metrics_rows)
            if not options["keep_cut_matrices"]:
                shutil.rmtree(matrix_dir, ignore_errors=True)

        model_path = output_dir / "future_link_online_logistic.joblib"
        joblib.dump(
            {
                "model_type": "online_logistic_sgd",
                "feature_names": list(LOGISTIC_FORWARD_FEATURES),
                "scaler": scaler,
                "classifier": classifier,
                "positive_weight": float(options["positive_weight"]),
                "alpha": float(options["alpha"]),
                "split_seed": split_config.seed,
                "test_percent": split_config.test_percent,
                "cut_count": len(plans),
            },
            model_path,
        )
        (output_dir / "run_metadata.json").write_text(
            json.dumps(
                {
                    "model_path": str(model_path),
                    "metrics_path": str(output_dir / "cut_metrics.jsonl"),
                    "cut_count": len(plans),
                    "positive_weight": float(options["positive_weight"]),
                    "alpha": float(options["alpha"]),
                    "features": list(LOGISTIC_FORWARD_FEATURES),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        gcs_output_uri = str(options["gcs_output_uri"] or "")
        if gcs_output_uri:
            upload_path_to_gcs(local_path=output_dir, gcs_uri=gcs_output_uri)
            self.stdout.write(self.style.SUCCESS(f"Uploaded outputs to {gcs_output_uri}"))
        self.stdout.write(self.style.SUCCESS(f"Finished {len(plans)} cut(s). Output: {output_dir}"))


def parse_cutoff(value: str):
    from datetime import datetime

    from django.utils import timezone

    parsed = datetime.fromisoformat(value)
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
