from __future__ import annotations

from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction
from django.db.models import QuerySet

from podcast_network.entity_aliases import KNOWN_PERSON_ALIASES, KnownPersonAlias
from podcast_network.web.catalog.models import (
    CanonicalPersonEntity,
    PersonEntityLink,
    PersonObservation,
)

KNOWN_ALIAS_METHOD = "known_person_alias"


@dataclass(frozen=True)
class KnownAliasStats:
    rules_seen: int = 0
    rules_applied: int = 0
    links_updated: int = 0


class Command(BaseCommand):
    help = "Apply deterministic known person alias mappings to entity links."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args: object, **options: object) -> None:
        stats = apply_known_person_entity_aliases(dry_run=bool(options["dry_run"]))
        action = "Would apply" if options["dry_run"] else "Applied"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} known person aliases: {stats.rules_seen} rules seen, "
                f"{stats.rules_applied} rules applied, {stats.links_updated} links updated."
            )
        )


def apply_known_person_entity_aliases(*, dry_run: bool = False) -> KnownAliasStats:
    rules_applied = 0
    links_updated = 0
    with transaction.atomic():
        for rule in KNOWN_PERSON_ALIASES:
            target = CanonicalPersonEntity.objects.filter(
                normalized_name=rule.target_normalized_name
            ).first()
            if target is None:
                continue
            links = links_for_rule(rule)
            link_count = links.exclude(canonical=target).count()
            if link_count == 0:
                continue
            rules_applied += 1
            links_updated += link_count
            if dry_run:
                continue
            links.update(
                canonical=target,
                match_method=KNOWN_ALIAS_METHOD,
                match_probability=1.0,
            )
            add_aliases_to_target(target, links)
    return KnownAliasStats(
        rules_seen=len(KNOWN_PERSON_ALIASES),
        rules_applied=rules_applied,
        links_updated=links_updated,
    )


def links_for_rule(rule: KnownPersonAlias) -> QuerySet[PersonEntityLink]:
    links = PersonEntityLink.objects.filter(
        observation__normalized_name=rule.alias_normalized_name
    )
    if rule.podcast_name:
        links = links.filter(observation__podcast__name=rule.podcast_name)
    return links


def add_aliases_to_target(
    target: CanonicalPersonEntity,
    links: QuerySet[PersonEntityLink],
) -> None:
    observed_names = (
        PersonObservation.objects.filter(
            observation_id__in=links.values_list("observation_id", flat=True)
        )
        .order_by("observed_name")
        .values_list("observed_name", flat=True)
        .distinct()
    )
    aliases = list(target.aliases or [])
    original_aliases = set(aliases)
    aliases.extend(name for name in observed_names if name not in original_aliases)
    if len(aliases) != len(original_aliases):
        target.aliases = sorted(aliases)
        target.save(update_fields=["aliases", "updated_at"])
