from __future__ import annotations

import json
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser

from podcast_network.artifact_metadata import current_git_sha, local_file_artifact_metadata
from podcast_network.cloud_artifacts import upload_path_to_gcs, upload_text_to_gcs
from podcast_network.paths import PROJECT_ROOT
from podcast_network.web.explorer.graph_artifact import write_graph_artifact
from podcast_network.web.explorer.graph_service import build_database_six_degrees_graph


class Command(BaseCommand):
    help = "Build a serialized six-degrees graph artifact for fast web path lookups."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--output",
            default="data/artifacts/six_degrees_graph.pkl.gz",
            help="Local path where the serialized graph artifact should be written.",
        )
        parser.add_argument(
            "--gcs-output-uri",
            default="",
            help="Optional exact gs:// URI where the graph artifact should be uploaded.",
        )

    def handle(self, *args: object, **options: object) -> None:
        output_path = Path(str(options["output"]))
        started = time.monotonic()
        graph = build_database_six_degrees_graph()
        build_seconds = time.monotonic() - started

        metadata = write_graph_artifact(
            graph=graph,
            path=output_path,
            metadata={
                "build_seconds": round(build_seconds, 3),
                "git_sha": current_git_sha(cwd=PROJECT_ROOT),
            },
        )
        file_metadata = local_file_artifact_metadata(output_path)
        metadata = {
            **metadata,
            "sha256": file_metadata["sha256"],
            "size_bytes": file_metadata["size_bytes"],
        }
        metadata_path = graph_metadata_path(output_path)
        metadata_path.write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Wrote graph artifact to {output_path} "
                f"({metadata['size_bytes']} bytes, {graph.person_count} people, "
                f"{graph.podcast_count} podcasts) in {build_seconds:.1f}s."
            )
        )

        gcs_output_uri = str(
            options["gcs_output_uri"] or settings.SIX_DEGREES_GRAPH_ARTIFACT_GCS_URI
        )
        if gcs_output_uri:
            upload_path_to_gcs(local_path=output_path, gcs_uri=gcs_output_uri)
            upload_text_to_gcs(
                text=metadata_path.read_text(encoding="utf-8"),
                gcs_uri=f"{gcs_output_uri}.json",
                content_type="application/json",
            )
            self.stdout.write(self.style.SUCCESS(f"Uploaded graph artifact to {gcs_output_uri}."))


def graph_metadata_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.json")
