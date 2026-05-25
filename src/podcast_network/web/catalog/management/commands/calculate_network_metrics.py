from __future__ import annotations

from django.core.management.base import BaseCommand, CommandParser

from podcast_network.network_metrics import calculate_and_store_network_metrics


class Command(BaseCommand):
    help = "Calculate network centrality metrics and store a Postgres snapshot."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--run-label", default="")

    def handle(self, *args: object, **options: object) -> None:
        run = calculate_and_store_network_metrics(run_label=str(options["run_label"]))
        self.stdout.write(
            self.style.SUCCESS(
                f"Network metric run {run.id} {run.status}: "
                f"{run.person_nodes} person nodes, {run.person_edges} person edges, "
                f"{run.podcast_nodes} podcast nodes, {run.podcast_edges} podcast edges."
            )
        )
