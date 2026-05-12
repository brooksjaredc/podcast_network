from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from django.core.management.base import BaseCommand, CommandParser

from podcast_network.entity_features import (
    HEURISTIC_MODEL_NAME,
    apply_entity_score_guards,
    heuristic_person_match_score,
)
from podcast_network.entity_model import load_entity_model, predict_match_probability
from podcast_network.web.catalog.models import PersonEntityCandidatePair


@dataclass(frozen=True)
class CandidateScoringStats:
    candidates_seen: int = 0
    candidates_scored: int = 0
    accepted: int = 0
    rejected: int = 0
    model_name: str = ""


class Command(BaseCommand):
    help = "Score person entity candidate pairs with a transparent local heuristic baseline."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--chunk-size", type=int, default=5000)
        parser.add_argument("--model-name", default=HEURISTIC_MODEL_NAME)
        parser.add_argument(
            "--trained-model",
            default="",
            help="Path to a trained sklearn entity model artifact. Defaults to heuristic scoring.",
        )
        parser.add_argument("--accept-threshold", type=float, default=0.5)
        parser.add_argument("--reject-threshold", type=float, default=0.35)
        parser.add_argument(
            "--auto-status",
            action="store_true",
            help="Mark rows above/below thresholds as accepted/rejected. Default only scores.",
        )
        parser.add_argument(
            "--report",
            default="",
            help="Optional Markdown report of top scored candidates.",
        )
        parser.add_argument("--report-limit", type=int, default=50)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args: object, **options: object) -> None:
        stats = score_person_entity_candidates(
            limit=int(options["limit"]),
            chunk_size=int(options["chunk_size"]),
            model_name=str(options["model_name"]),
            trained_model_path=str(options["trained_model"]),
            accept_threshold=float(options["accept_threshold"]),
            reject_threshold=float(options["reject_threshold"]),
            auto_status=bool(options["auto_status"]),
            dry_run=bool(options["dry_run"]),
        )
        if options["report"]:
            write_score_report(
                path=Path(str(options["report"])),
                limit=int(options["report_limit"]),
                model_name=stats.model_name,
            )
        action = "Would score" if options["dry_run"] else "Scored"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} person entity candidates: {stats.candidates_seen} seen, "
                f"{stats.candidates_scored} scored, {stats.accepted} accepted, "
                f"{stats.rejected} rejected."
            )
        )


def score_person_entity_candidates(
    *,
    limit: int = 0,
    chunk_size: int = 5000,
    model_name: str = HEURISTIC_MODEL_NAME,
    trained_model_path: str = "",
    accept_threshold: float = 0.5,
    reject_threshold: float = 0.35,
    auto_status: bool = False,
    dry_run: bool = False,
) -> CandidateScoringStats:
    trained_model = load_entity_model(Path(trained_model_path)) if trained_model_path else None
    if trained_model is not None:
        model_name = trained_model.model_name
    queryset = PersonEntityCandidatePair.objects.order_by("pair_id")
    if limit:
        queryset = queryset[:limit]
    updates = []
    seen = 0
    accepted = 0
    rejected = 0
    for pair in queryset.iterator(chunk_size=chunk_size):
        seen += 1
        reasons = []
        if trained_model is None:
            score, reasons = heuristic_person_match_score(pair.features)
        else:
            score = predict_match_probability(trained_model, pair.features)
            score, reasons = apply_entity_score_guards(score, pair.features)
        pair.match_probability = score
        pair.model_name = model_name
        if trained_model is None or reasons:
            pair.features = {**pair.features, "heuristic_reasons": reasons}
        if auto_status and score >= accept_threshold:
            pair.status = PersonEntityCandidatePair.Status.ACCEPTED
            accepted += 1
        elif auto_status and score <= reject_threshold:
            pair.status = PersonEntityCandidatePair.Status.REJECTED
            rejected += 1
        updates.append(pair)

    if not dry_run and updates:
        PersonEntityCandidatePair.objects.bulk_update(
            updates,
            fields=["match_probability", "model_name", "features", "status", "updated_at"],
            batch_size=chunk_size,
        )
    return CandidateScoringStats(
        candidates_seen=seen,
        candidates_scored=len(updates),
        accepted=accepted,
        rejected=rejected,
        model_name=model_name,
    )


def write_score_report(*, path: Path, limit: int, model_name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = PersonEntityCandidatePair.objects.filter(model_name=model_name).order_by(
        "-match_probability",
        "left__display_name",
        "right__display_name",
    )[:limit]
    lines = [
        "# Person Entity Candidate Scores",
        "",
        f"Model: `{model_name}`",
        "",
        "| Score | Left | Right | Shared Podcasts | Token Jaccard | Reasons |",
        "|---:|---|---|---:|---:|---|",
    ]
    for pair in rows:
        features = pair.features or {}
        reasons = ", ".join(features.get("heuristic_reasons") or [])
        lines.append(
            f"| {pair.match_probability or 0:.3f} | {pair.left.display_name} | "
            f"{pair.right.display_name} | {features.get('shared_podcast_count', 0)} | "
            f"{features.get('token_jaccard', 0):.3f} | {reasons} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
