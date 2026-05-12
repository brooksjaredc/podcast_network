from __future__ import annotations

import ast
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from podcast_network.paths import PROJECT_ROOT
from podcast_network.web.catalog.management.commands.migrate_legacy_hosts import (
    migrate_legacy_hosts,
)
from podcast_network.web.catalog.models import Feed, Podcast

DEFAULT_LEGACY_FEED_PATH = (
    PROJECT_ROOT.parent
    / "podcast_network_analysis"
    / "analyzing_functions"
    / "meta_podcast_info.csv"
)


@dataclass(frozen=True)
class ImportResult:
    podcasts_created: int = 0
    podcasts_updated: int = 0
    feeds_created: int = 0
    feeds_updated: int = 0


class Command(BaseCommand):
    help = "Import legacy podcast RSS feed URLs from meta_podcast_info.csv."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "path",
            nargs="?",
            default=str(DEFAULT_LEGACY_FEED_PATH),
            help="Path to legacy tab-separated meta_podcast_info.csv.",
        )

    def handle(self, *args: object, **options: object) -> None:
        path = Path(str(options["path"])).expanduser()
        if not path.exists():
            raise CommandError(f"Legacy feed file does not exist: {path}")

        result = import_legacy_feeds(path)
        self.stdout.write(
            self.style.SUCCESS(
                "Imported legacy feeds: "
                f"{result.podcasts_created} podcasts created, "
                f"{result.podcasts_updated} podcasts updated, "
                f"{result.feeds_created} feeds created, "
                f"{result.feeds_updated} feeds updated."
            )
        )


def import_legacy_feeds(path: Path) -> ImportResult:
    result = ImportResult()
    with path.open(newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file, delimiter="\t")
        for record in reader:
            result = add_results(result, import_record(record))
    migrate_legacy_hosts(run_label=f"legacy-feed-import:{path.name}")
    return result


def import_record(record: dict[str, str]) -> ImportResult:
    podcast_name = clean(record.get("Podcast Name"))
    feed_url = clean(record.get("feedURL"))
    if not podcast_name or not feed_url:
        return ImportResult()

    legacy_index = clean(record.get("") or record.get("id"))
    legacy_podcast_id = legacy_id_from_index(legacy_index)
    podcast, podcast_created = Podcast.objects.update_or_create(
        name=podcast_name,
        defaults={
            "description": clean(record.get("description")),
            "image_url": clean(record.get("imageURL")),
            "external_id": legacy_podcast_id,
            "metadata": legacy_metadata(record),
        },
    )
    feed, feed_created = Feed.objects.get_or_create(
        url=feed_url,
        defaults={
            "podcast": podcast,
            "active": bool_value(record.get("active"), default=True),
            "parser_hint": clean(record.get("cleaner")),
        },
    )
    if not feed_created:
        feed.podcast = podcast
        feed.active = bool_value(record.get("active"), default=feed.active)
        feed.parser_hint = clean(record.get("cleaner"))
        feed.save(update_fields=["podcast", "active", "parser_hint", "updated_at"])

    return ImportResult(
        podcasts_created=int(podcast_created),
        podcasts_updated=int(not podcast_created),
        feeds_created=int(feed_created),
        feeds_updated=int(not feed_created),
    )


def legacy_metadata(record: dict[str, str]) -> dict[str, Any]:
    keys = [
        "Hosts",
        "categories",
        "keywords",
        "cleaner",
        "percent_unique",
        "num_guests",
        "num_unique",
        "avg_day_diff",
        "active",
        "premier",
        "avg_ep_lengths",
        "cat_bias",
        "hub_leader_score",
        "bt_diff_leader_score",
    ]
    metadata = {
        "legacy": {
            "source": "podcast_network_analysis/analyzing_functions/meta_podcast_info.csv",
            "podcast_id": legacy_id_from_index(clean(record.get("") or record.get("id"))),
        }
    }
    for key in keys:
        value = clean(record.get(key))
        if value:
            metadata["legacy"][normalized_key(key)] = parsed_value(value)
    return metadata


def parsed_value(value: str) -> Any:
    if value.startswith("[") and value.endswith("]"):
        try:
            return ast.literal_eval(value)
        except (SyntaxError, ValueError):
            return value
    if value in {"True", "False"}:
        return value == "True"
    return value


def bool_value(value: str | None, *, default: bool) -> bool:
    normalized = clean(value).lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    return default


def legacy_id_from_index(value: str) -> str:
    if not value:
        return ""
    try:
        return str(int(value) - 1)
    except ValueError:
        return value


def normalized_key(value: str) -> str:
    return value.lower().replace(" ", "_")


def clean(value: str | None) -> str:
    return (value or "").strip()


def add_results(first: ImportResult, second: ImportResult) -> ImportResult:
    return ImportResult(
        podcasts_created=first.podcasts_created + second.podcasts_created,
        podcasts_updated=first.podcasts_updated + second.podcasts_updated,
        feeds_created=first.feeds_created + second.feeds_created,
        feeds_updated=first.feeds_updated + second.feeds_updated,
    )
