from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandParser

from podcast_network.future_links.model import run_logistic_grid_search, write_logistic_grid_result


class Command(BaseCommand):
    help = "Run logistic-regression hyperparameter grid search on a stored feature matrix."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--matrix-dir", default="data/reports/future_link_full_matrix")
        parser.add_argument("--output", default="data/reports/future_link_logistic_grid.json")
        parser.add_argument(
            "--c-values",
            default="0.01,0.1,1,10",
            help="Comma-separated logistic C values.",
        )
        parser.add_argument(
            "--class-weights",
            default="none,balanced,10,50,100,500,1000",
            help=(
                "Comma-separated class weights. Use none, balanced, or a numeric positive-class "
                "weight with negative class fixed at 1."
            ),
        )
        parser.add_argument("--random-state", type=int, default=42)
        parser.add_argument("--max-iter", type=int, default=300)

    def handle(self, *args: object, **options: object) -> None:
        result = run_logistic_grid_search(
            matrix_dir=Path(str(options["matrix_dir"])),
            c_values=parse_float_list(str(options["c_values"])),
            class_weight_values=parse_string_list(str(options["class_weights"])),
            random_state=int(options["random_state"]),
            max_iter=int(options["max_iter"]),
        )
        output = Path(str(options["output"]))
        write_logistic_grid_result(result, output)
        self.stdout.write(self.style.SUCCESS(f"Wrote logistic grid results: {output}"))
        self.stdout.write("Top results by average precision:")
        for row in result.results[:10]:
            self.stdout.write(json.dumps(row, sort_keys=True))


def parse_float_list(value: str) -> list[float]:
    return [float(item.strip()) for item in value.split(",") if item.strip()]


def parse_string_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]
