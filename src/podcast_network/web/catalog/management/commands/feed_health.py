from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from pathlib import Path

from django.core.management.base import BaseCommand, CommandParser
from django.db.models import Count, Max

from podcast_network.web.catalog.models import Feed


@dataclass(frozen=True)
class FeedHealthRow:
    podcast: str
    url: str
    active: bool
    last_status: int | None
    failure_count: int
    episode_count: int
    newest_episode: str
    last_fetched_at: str
    parser_hint: str


class Command(BaseCommand):
    help = "Report feed scrape health and parsed episode coverage."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--csv",
            dest="csv_path",
            default="",
            help="Write the detailed report to a CSV file.",
        )
        parser.add_argument(
            "--show",
            type=int,
            default=15,
            help="Number of problem rows to print.",
        )

    def handle(self, *args: object, **options: object) -> None:
        rows = feed_health_rows()
        print_summary(rows, self.stdout.write)
        print_problem_rows(rows, int(options["show"]), self.stdout.write)

        csv_path = str(options["csv_path"])
        if csv_path:
            write_csv(rows, Path(csv_path))
            self.stdout.write(self.style.SUCCESS(f"Wrote feed health CSV to {csv_path}"))


def feed_health_rows() -> list[FeedHealthRow]:
    feeds = (
        Feed.objects.select_related("podcast")
        .annotate(
            episode_count=Count("podcast__episodes", distinct=True),
            newest_episode=Max("podcast__episodes__published_at"),
        )
        .order_by("podcast__name")
    )
    return [
        FeedHealthRow(
            podcast=feed.podcast.name,
            url=feed.url,
            active=feed.active,
            last_status=feed.last_status,
            failure_count=feed.failure_count,
            episode_count=feed.episode_count,
            newest_episode=feed.newest_episode.isoformat() if feed.newest_episode else "",
            last_fetched_at=feed.last_fetched_at.isoformat() if feed.last_fetched_at else "",
            parser_hint=feed.parser_hint,
        )
        for feed in feeds
    ]


def print_summary(rows: list[FeedHealthRow], write) -> None:
    total = len(rows)
    active = sum(row.active for row in rows)
    fetched = sum(row.last_fetched_at != "" for row in rows)
    succeeded = sum((row.last_status or 0) < 400 and row.last_status is not None for row in rows)
    failed = sum(row.failure_count > 0 for row in rows)
    zero_episode = sum(row.episode_count == 0 for row in rows)
    total_episodes = sum(row.episode_count for row in rows)
    write(
        "Feed health: "
        f"{total} feeds, {active} active, {fetched} fetched, "
        f"{succeeded} last-success, {failed} with failures, "
        f"{zero_episode} with zero episodes, {total_episodes} parsed episodes."
    )


def print_problem_rows(rows: list[FeedHealthRow], limit: int, write) -> None:
    problems = [
        row
        for row in rows
        if row.failure_count > 0 or row.episode_count == 0 or (row.last_status or 0) >= 400
    ][:limit]
    if not problems:
        return
    write("Problem feeds:")
    for row in problems:
        write(
            f"- {row.podcast}: status={row.last_status or 'none'}, "
            f"failures={row.failure_count}, episodes={row.episode_count}, url={row.url}"
        )


def write_csv(rows: list[FeedHealthRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(FeedHealthRow.__annotations__))
        writer.writeheader()
        for row in rows:
            writer.writerow(row.__dict__)


if __name__ == "__main__":
    write_csv(feed_health_rows(), Path(sys.argv[1]))
