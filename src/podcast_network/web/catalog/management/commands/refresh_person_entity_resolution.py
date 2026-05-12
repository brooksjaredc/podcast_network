from __future__ import annotations

from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandParser

CURRENT_ENTITY_MODEL = Path("data/models/person_entity_xgboost_namefreq_groups_v1.joblib")
CURRENT_ENTITY_MODEL_NAME = "person-entity-xgboost-namefreq-groups-v1"


class Command(BaseCommand):
    help = "Refresh person entity resolution after guest appearance sync."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--model", default=str(CURRENT_ENTITY_MODEL))
        parser.add_argument("--min-score", type=float, default=0.5)
        parser.add_argument("--limit-pairs", type=int, default=10000)
        parser.add_argument("--min-observations", type=int, default=1)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args: object, **options: object) -> None:
        model_path = Path(str(options["model"]))
        if not model_path.exists():
            self.stderr.write(self.style.ERROR(f"Model not found: {model_path}"))
            return
        call_command("sync_person_entities", dry_run=bool(options["dry_run"]))
        call_command(
            "generate_person_entity_candidates",
            limit_pairs=int(options["limit_pairs"]),
            min_observations=int(options["min_observations"]),
            dry_run=bool(options["dry_run"]),
        )
        if options["dry_run"]:
            self.stdout.write(
                self.style.SUCCESS("Dry run complete; skipped scoring and applying matches.")
            )
            return
        call_command("score_person_entity_candidates", trained_model=str(model_path))
        call_command(
            "apply_person_entity_matches",
            model_name=CURRENT_ENTITY_MODEL_NAME,
            min_score=float(options["min_score"]),
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Refreshed person entity resolution with {CURRENT_ENTITY_MODEL_NAME}."
            )
        )
