from __future__ import annotations

from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction

from podcast_network.web.catalog.models import (
    CanonicalPersonEntity,
    PersonEntityCandidatePair,
    PersonEntityLink,
)


@dataclass(frozen=True)
class ApplyEntityMatchStats:
    pairs_seen: int = 0
    pairs_applied: int = 0
    links_updated: int = 0


class Command(BaseCommand):
    help = "Apply high-confidence person entity candidate matches to observation links."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--model-name", default="person-entity-xgboost-namefreq-groups-v1")
        parser.add_argument("--min-score", type=float, default=0.97)
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args: object, **options: object) -> None:
        stats = apply_person_entity_matches(
            model_name=str(options["model_name"]),
            min_score=float(options["min_score"]),
            limit=int(options["limit"]),
            dry_run=bool(options["dry_run"]),
        )
        action = "Would apply" if options["dry_run"] else "Applied"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} person entity matches: {stats.pairs_seen} pairs seen, "
                f"{stats.pairs_applied} pairs applied, {stats.links_updated} links updated."
            )
        )


def apply_person_entity_matches(
    *,
    model_name: str = "person-entity-xgboost-namefreq-groups-v1",
    min_score: float = 0.97,
    limit: int = 0,
    dry_run: bool = False,
) -> ApplyEntityMatchStats:
    pairs = (
        PersonEntityCandidatePair.objects.filter(
            model_name=model_name,
            match_probability__gte=min_score,
        )
        .select_related("left", "right")
        .order_by("-match_probability", "pair_id")
    )
    if limit:
        pairs = pairs[:limit]

    pairs_seen = 0
    pairs_applied = 0
    links_updated = 0
    with transaction.atomic():
        for pair in pairs:
            pairs_seen += 1
            target, source = merge_target_and_source(pair.left, pair.right)
            source_links = PersonEntityLink.objects.filter(canonical=source)
            source_link_count = source_links.count()
            if source_link_count == 0:
                continue
            pairs_applied += 1
            links_updated += source_link_count
            if dry_run:
                continue
            source_links.update(
                canonical=target,
                match_method=f"ml_entity_resolution:{model_name}",
                match_probability=pair.match_probability or min_score,
            )
            pair.status = PersonEntityCandidatePair.Status.ACCEPTED
            pair.save(update_fields=["status", "updated_at"])
    return ApplyEntityMatchStats(
        pairs_seen=pairs_seen,
        pairs_applied=pairs_applied,
        links_updated=links_updated,
    )


def merge_target_and_source(
    left: CanonicalPersonEntity,
    right: CanonicalPersonEntity,
) -> tuple[CanonicalPersonEntity, CanonicalPersonEntity]:
    if left.observation_count != right.observation_count:
        return (left, right) if left.observation_count > right.observation_count else (right, left)
    if len(left.display_name) != len(right.display_name):
        return (left, right) if len(left.display_name) > len(right.display_name) else (right, left)
    if left.display_name.casefold() <= right.display_name.casefold():
        return left, right
    return right, left
