from __future__ import annotations

from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction
from django.db.models import Count, ExpressionWrapper, F, FloatField, Q, Value

from podcast_network.web.catalog.models import Appearance

DERIVED_COHOST_SOURCE = "derived-frequent-guest-cohost"
DEFAULT_COHOST_EPISODE_THRESHOLD = 100
DEFAULT_COHOST_EPISODE_SHARE = 0.20


@dataclass(frozen=True)
class PromotionStats:
    podcast_people_seen: int = 0
    pairs_promoted: int = 0
    host_appearances_created: int = 0
    guest_appearances_deleted: int = 0


class Command(BaseCommand):
    help = "Promote recurring guest/podcast pairs to co-host-equivalent host appearances."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--threshold", type=int, default=DEFAULT_COHOST_EPISODE_THRESHOLD)
        parser.add_argument(
            "--episode-share-threshold",
            type=float,
            default=DEFAULT_COHOST_EPISODE_SHARE,
            help="Also promote people who guest on more than this share of a podcast's episodes.",
        )
        parser.add_argument(
            "--clear-existing",
            action="store_true",
            help="Delete previously derived co-host rows before recomputing promotions.",
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args: object, **options: object) -> None:
        stats = promote_frequent_guests_to_cohosts(
            threshold=int(options["threshold"]),
            episode_share_threshold=float(options["episode_share_threshold"]),
            clear_existing=bool(options["clear_existing"]),
            dry_run=bool(options["dry_run"]),
        )
        action = "Would promote" if options["dry_run"] else "Promoted"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} frequent guests to co-hosts: "
                f"{stats.podcast_people_seen} pairs seen, {stats.pairs_promoted} promoted, "
                f"{stats.host_appearances_created} host appearances created, "
                f"{stats.guest_appearances_deleted} guest appearances deleted."
            )
        )


def promote_frequent_guests_to_cohosts(
    *,
    threshold: int = DEFAULT_COHOST_EPISODE_THRESHOLD,
    episode_share_threshold: float = DEFAULT_COHOST_EPISODE_SHARE,
    clear_existing: bool = False,
    dry_run: bool = False,
) -> PromotionStats:
    episode_share_cutoff = ExpressionWrapper(
        F("podcast_episode_count") * Value(episode_share_threshold),
        output_field=FloatField(),
    )
    rows = list(
        Appearance.objects.filter(role=Appearance.Role.GUEST)
        .values("episode__podcast_id", "person_id")
        .annotate(
            guest_episode_count=Count("episode_id", distinct=True),
            podcast_episode_count=Count("episode__podcast__episodes", distinct=True),
        )
        .filter(
            Q(guest_episode_count__gt=threshold)
            | Q(guest_episode_count__gt=episode_share_cutoff)
        )
        .order_by("-guest_episode_count", "episode__podcast_id", "person_id")
    )
    host_appearances_created = 0
    guest_appearances_deleted = 0
    with transaction.atomic():
        if clear_existing and not dry_run:
            Appearance.objects.filter(source=DERIVED_COHOST_SOURCE).delete()
        for row in rows:
            guest_rows = Appearance.objects.filter(
                role=Appearance.Role.GUEST,
                episode__podcast_id=row["episode__podcast_id"],
                person_id=row["person_id"],
            )
            episode_ids = list(guest_rows.values_list("episode_id", flat=True))
            host_rows = [
                Appearance(
                    episode_id=episode_id,
                    person_id=row["person_id"],
                    role=Appearance.Role.HOST,
                    source=DERIVED_COHOST_SOURCE,
                    confidence=1.0,
                )
                for episode_id in episode_ids
            ]
            if dry_run:
                host_appearances_created += len(host_rows)
                guest_appearances_deleted += len(episode_ids)
                continue
            created = Appearance.objects.bulk_create(host_rows, ignore_conflicts=True)
            host_appearances_created += len(created)
            guest_appearances_deleted += guest_rows.count()
            guest_rows.delete()
    return PromotionStats(
        podcast_people_seen=len(rows),
        pairs_promoted=len(rows),
        host_appearances_created=host_appearances_created,
        guest_appearances_deleted=guest_appearances_deleted,
    )
