from __future__ import annotations

from django.core.management.base import BaseCommand, CommandParser

from podcast_network.network.metrics import calculate_and_store_network_metrics
from podcast_network.operational_safety import database_statement_timeout


class Command(BaseCommand):
    help = "Calculate network centrality metrics and store a Postgres snapshot."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--run-label", default="")
        parser.add_argument("--statement-timeout-ms", type=int, default=0)

    def handle(self, *args: object, **options: object) -> None:
        with database_statement_timeout(int(options["statement_timeout_ms"])):
            run = calculate_and_store_network_metrics(run_label=str(options["run_label"]))
        self.stdout.write(
            self.style.SUCCESS(
                f"Network metric run {run.id} {run.status}: "
                f"{run.person_nodes} person nodes, {run.person_edges} person edges, "
                f"{run.podcast_nodes} podcast nodes, {run.podcast_edges} podcast edges."
            )
        )
