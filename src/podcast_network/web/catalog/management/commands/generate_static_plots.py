from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandParser

from podcast_network.cloud_artifacts import upload_path_to_gcs
from podcast_network.plots import generate as plot_generate


class Command(BaseCommand):
    help = "Regenerate static advanced plot assets."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--output-dir",
            default="static/plots",
            help="Directory where plot assets should be written.",
        )
        parser.add_argument(
            "--gcs-output-uri",
            default="",
            help="Optional gs:// URI prefix to upload regenerated plot assets.",
        )

    def handle(self, *args: object, **options: object) -> None:
        output_dir = Path(str(options["output_dir"]))
        plot_generate.PLOTS_DIR = output_dir
        outputs = plot_generate.generate_all_plots()
        self.stdout.write(self.style.SUCCESS(f"Generated {len(outputs)} plot assets."))
        gcs_output_uri = str(options["gcs_output_uri"])
        if gcs_output_uri:
            upload_path_to_gcs(local_path=output_dir, gcs_uri=gcs_output_uri)
            self.stdout.write(self.style.SUCCESS(f"Uploaded plots to {gcs_output_uri}."))
