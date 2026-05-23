from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandParser

from podcast_network.future_link_model import (
    save_future_link_model,
    train_future_link_model,
    write_future_link_metrics,
)


class Command(BaseCommand):
    help = "Train a local future-link experiment model from a balanced feature CSV."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--dataset",
            default="data/reports/future_link_experiment_dataset.csv",
        )
        parser.add_argument("--model-type", choices=["logistic", "xgboost"], default="xgboost")
        parser.add_argument("--output", default="data/models/future_link_experiment.joblib")
        parser.add_argument("--metrics-output", default="data/reports/future_link_metrics.json")
        parser.add_argument("--random-state", type=int, default=42)
        parser.add_argument("--forward-selection", action="store_true")
        parser.add_argument("--max-features", type=int, default=12)

    def handle(self, *args: object, **options: object) -> None:
        result = train_future_link_model(
            dataset_path=Path(str(options["dataset"])),
            model_type=str(options["model_type"]),
            forward_selection=bool(options["forward_selection"]),
            max_features=int(options["max_features"]),
            random_state=int(options["random_state"]),
        )
        output = Path(str(options["output"]))
        metrics_output = Path(str(options["metrics_output"]))
        save_future_link_model(result, output)
        write_future_link_metrics(result, metrics_output)
        self.stdout.write(
            self.style.SUCCESS(
                f"Trained {result.model_type} future-link model with "
                f"{len(result.feature_names)} feature(s). Model: {output}. "
                f"Metrics: {metrics_output}."
            )
        )
        self.stdout.write(json.dumps(result.metrics, indent=2, sort_keys=True))
        self.stdout.write("Features:")
        for feature_name in result.feature_names:
            self.stdout.write(f"  {feature_name}")

