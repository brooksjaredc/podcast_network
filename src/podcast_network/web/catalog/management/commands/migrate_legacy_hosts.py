from __future__ import annotations

from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction
from django.utils import timezone

from podcast_network.cleaning import clean_person_display_name, is_single_token_person_name
from podcast_network.extraction.pipeline import normalize_name
from podcast_network.web.catalog.models import (
    ExtractionRun,
    HostCandidate,
    Podcast,
    PodcastHostExtraction,
)

PROMPT_VERSION = "legacy-host-import-v1"
MODEL = "legacy-metadata"
PROVIDER = "legacy"


@dataclass(frozen=True)
class MigrationStats:
    podcasts_seen: int = 0
    podcasts_with_hosts: int = 0
    candidates_created: int = 0
    skipped_single_name_hosts: int = 0


class Command(BaseCommand):
    help = "Move legacy podcast host metadata into host extraction tables."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--run-label", default="legacy-host-import")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Count legacy hosts without writing host extraction rows.",
        )

    def handle(self, *args: object, **options: object) -> None:
        stats = migrate_legacy_hosts(
            run_label=str(options["run_label"]),
            dry_run=bool(options["dry_run"]),
        )
        action = "Found" if options["dry_run"] else "Migrated"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} legacy hosts: {stats.podcasts_seen} podcasts checked, "
                f"{stats.podcasts_with_hosts} with host metadata, "
                f"{stats.candidates_created} host candidates, "
                f"{stats.skipped_single_name_hosts} single-name hosts skipped."
            )
        )


def migrate_legacy_hosts(*, run_label: str, dry_run: bool = False) -> MigrationStats:
    run = None
    if not dry_run:
        run = ExtractionRun.objects.create(
            model=MODEL,
            provider=PROVIDER,
            prompt_version=PROMPT_VERSION,
            status=ExtractionRun.Status.RUNNING,
            metadata={
                "run_label": run_label,
                "purpose": "legacy-host-import",
                "source": "podcast.metadata.legacy.hosts",
            },
        )

    stats = MigrationStats()
    for podcast in Podcast.objects.only("id", "name", "metadata").iterator(chunk_size=1000):
        hosts = legacy_hosts(podcast)
        stats = MigrationStats(
            podcasts_seen=stats.podcasts_seen + 1,
            podcasts_with_hosts=stats.podcasts_with_hosts + int(bool(hosts)),
            candidates_created=stats.candidates_created,
            skipped_single_name_hosts=stats.skipped_single_name_hosts,
        )
        if not hosts:
            continue
        candidate_names, skipped = clean_host_names(hosts)
        stats = MigrationStats(
            podcasts_seen=stats.podcasts_seen,
            podcasts_with_hosts=stats.podcasts_with_hosts,
            candidates_created=stats.candidates_created + len(candidate_names),
            skipped_single_name_hosts=stats.skipped_single_name_hosts + skipped,
        )
        if dry_run:
            continue
        persist_legacy_host_extraction(
            podcast=podcast,
            run=run,
            candidate_names=candidate_names,
            source_hosts=hosts,
        )

    if run is not None:
        run.episodes_requested = stats.podcasts_with_hosts
        run.episodes_succeeded = stats.podcasts_with_hosts
        run.episodes_failed = 0
        run.status = ExtractionRun.Status.SUCCEEDED
        run.finished_at = timezone.now()
        run.save()
    return stats


def persist_legacy_host_extraction(
    *,
    podcast: Podcast,
    run: ExtractionRun,
    candidate_names: list[str],
    source_hosts: list[str],
) -> None:
    with transaction.atomic():
        extraction, _ = PodcastHostExtraction.objects.update_or_create(
            podcast=podcast,
            prompt_version=PROMPT_VERSION,
            model=MODEL,
            defaults={
                "extraction_run": run,
                "status": PodcastHostExtraction.Status.SUCCEEDED,
                "input_text": "\n".join(source_hosts),
                "raw_response": {"hosts": source_hosts, "source": "legacy_metadata"},
                "error": "",
                "input_tokens": 0,
                "output_tokens": 0,
            },
        )
        extraction.host_candidates.all().delete()
        HostCandidate.objects.bulk_create(
            [
                HostCandidate(
                    extraction=extraction,
                    name=name,
                    normalized_name=normalize_name(name),
                    kind=HostCandidate.Kind.HOST,
                    confidence=1.0,
                    evidence="Imported from legacy podcast host metadata.",
                    accepted=True,
                )
                for name in candidate_names
            ]
        )


def legacy_hosts(podcast: Podcast) -> list[str]:
    legacy = (podcast.metadata or {}).get("legacy") or {}
    hosts = legacy.get("hosts") or []
    if not isinstance(hosts, list):
        return []
    return [str(host).strip() for host in hosts if str(host).strip()]


def clean_host_names(hosts: list[str]) -> tuple[list[str], int]:
    names = []
    seen = set()
    skipped = 0
    for host in hosts:
        display_name = clean_person_display_name(host)
        normalized = normalize_name(display_name)
        if not normalized:
            continue
        if is_single_token_person_name(display_name):
            skipped += 1
            continue
        if normalized in seen:
            continue
        names.append(display_name)
        seen.add(normalized)
    return names, skipped
