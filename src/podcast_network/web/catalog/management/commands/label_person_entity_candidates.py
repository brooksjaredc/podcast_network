from __future__ import annotations

from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandParser

from podcast_network.web.catalog.models import (
    PersonEntityCandidatePair,
    PersonEntityPairLabel,
)


@dataclass(frozen=True)
class LabelingStats:
    shown: int = 0
    matches: int = 0
    not_matches: int = 0
    skipped: int = 0


class Command(BaseCommand):
    help = "Interactively label uncertain person entity candidate pairs for active learning."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--limit", type=int, default=25)
        parser.add_argument("--min-score", type=float, default=0.35)
        parser.add_argument("--max-score", type=float, default=0.85)
        parser.add_argument(
            "--include-labeled",
            action="store_true",
            help="Include pairs that already have human labels.",
        )
        parser.add_argument(
            "--order",
            choices=["uncertain", "score_asc", "score_desc"],
            default="uncertain",
        )
        parser.add_argument("--source", default="human_active_learning")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Display candidates but do not persist labels.",
        )

    def handle(self, *args: object, **options: object) -> None:
        pairs = select_labeling_candidates(
            limit=int(options["limit"]),
            min_score=float(options["min_score"]),
            max_score=float(options["max_score"]),
            include_labeled=bool(options["include_labeled"]),
            order=str(options["order"]),
        )
        if not pairs:
            self.stdout.write(self.style.WARNING("No candidate pairs selected for labeling."))
            return
        stats = interactive_label_pairs(
            pairs=pairs,
            source=str(options["source"]),
            dry_run=bool(options["dry_run"]),
            input_func=input,
            output_func=self.stdout.write,
        )
        action = "Would save" if options["dry_run"] else "Saved"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} labels: {stats.shown} shown, {stats.matches} match, "
                f"{stats.not_matches} not match, {stats.skipped} skipped."
            )
        )


def select_labeling_candidates(
    *,
    limit: int,
    min_score: float,
    max_score: float,
    include_labeled: bool,
    order: str,
) -> list[PersonEntityCandidatePair]:
    queryset = PersonEntityCandidatePair.objects.select_related("left", "right").filter(
        match_probability__isnull=False,
        match_probability__gte=min_score,
        match_probability__lte=max_score,
    )
    if not include_labeled:
        queryset = queryset.filter(labels__isnull=True)
    if order == "score_asc":
        queryset = queryset.order_by(
            "match_probability",
            "left__display_name",
            "right__display_name",
        )
    elif order == "score_desc":
        queryset = queryset.order_by(
            "-match_probability",
            "left__display_name",
            "right__display_name",
        )
    else:
        queryset = sorted(
            queryset,
            key=lambda pair: (
                abs((pair.match_probability or 0) - 0.5),
                pair.left.display_name,
                pair.right.display_name,
            ),
        )
        return list(queryset[:limit])
    return list(queryset[:limit])


def interactive_label_pairs(
    *,
    pairs: list[PersonEntityCandidatePair],
    source: str,
    dry_run: bool,
    input_func,
    output_func,
) -> LabelingStats:
    stats = LabelingStats()
    for index, pair in enumerate(pairs, start=1):
        output_func(format_pair_for_labeling(pair, index=index, total=len(pairs)))
        answer = prompt_for_label(input_func)
        if answer == "q":
            break
        label = answer_to_label(answer)
        if label is None:
            continue
        stats = increment_stats(stats, label)
        if not dry_run:
            PersonEntityPairLabel.objects.create(
                pair=pair,
                pair_id_snapshot=pair.pair_id,
                label=label,
                source=source,
                model_name=pair.model_name,
                match_probability=pair.match_probability,
                features=pair.features,
            )
    return stats


def prompt_for_label(input_func) -> str:
    while True:
        answer = input_func("Label [y=yes match, n=not match, s=skip, q=quit]: ").strip().lower()
        if answer in {"y", "n", "s", "q"}:
            return answer
        print("Please enter y, n, s, or q.")


def answer_to_label(answer: str) -> str | None:
    if answer == "y":
        return PersonEntityPairLabel.Label.MATCH
    if answer == "n":
        return PersonEntityPairLabel.Label.NOT_MATCH
    if answer == "s":
        return PersonEntityPairLabel.Label.SKIP
    return None


def increment_stats(stats: LabelingStats, label: str) -> LabelingStats:
    return LabelingStats(
        shown=stats.shown + 1,
        matches=stats.matches + int(label == PersonEntityPairLabel.Label.MATCH),
        not_matches=stats.not_matches + int(label == PersonEntityPairLabel.Label.NOT_MATCH),
        skipped=stats.skipped + int(label == PersonEntityPairLabel.Label.SKIP),
    )


def format_pair_for_labeling(
    pair: PersonEntityCandidatePair,
    *,
    index: int,
    total: int,
) -> str:
    features = pair.features or {}
    lines = [
        "",
        f"Candidate {index}/{total}",
        "=" * 72,
        f"Left:  {pair.left.display_name}  [{pair.left.normalized_name}]",
        f"Right: {pair.right.display_name}  [{pair.right.normalized_name}]",
        f"Score: {(pair.match_probability or 0):.3f}    Model: {pair.model_name or 'unscored'}",
        f"Blocking keys: {', '.join(pair.blocking_keys or [])}",
        "",
        "Features:",
    ]
    for key in feature_display_order():
        if key in features:
            lines.append(f"  {key}: {features[key]}")
    reasons = features.get("heuristic_reasons") or []
    if reasons:
        lines.extend(["", f"Heuristic reasons: {', '.join(reasons)}"])
    return "\n".join(lines)


def feature_display_order() -> list[str]:
    return [
        "name_sequence_ratio",
        "token_jaccard",
        "token_overlap_count",
        "same_token_set",
        "one_name_contains_other_tokens",
        "same_first_token",
        "same_last_token",
        "left_observation_count",
        "right_observation_count",
        "shared_podcast_count",
        "podcast_jaccard",
        "shared_genre_count",
        "genre_jaccard",
        "both_host_somewhere",
        "both_guest_somewhere",
        "role_jaccard",
        "graph_distance_proxy",
        "has_graph_distance_proxy",
    ]
