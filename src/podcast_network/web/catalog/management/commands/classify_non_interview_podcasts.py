from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from django.core.management.base import BaseCommand, CommandParser
from django.db.models import Count, Q

from podcast_network.web.catalog.models import Feed, Podcast


@dataclass(frozen=True)
class PodcastClassification:
    podcast: Podcast
    episode_count: int
    guest_episode_count: int
    guest_episode_ratio: float


class Command(BaseCommand):
    help = "Mark low-guest-ratio podcasts as non-interview feeds to skip future work."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--threshold", type=float, default=0.05)
        parser.add_argument("--min-episodes", type=int, default=20)
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Persist metadata flags and deactivate feeds. Default is report-only.",
        )
        parser.add_argument(
            "--report",
            default="data/reports/non_interview_podcasts.md",
            help="Markdown report path.",
        )

    def handle(self, *args: object, **options: object) -> None:
        threshold = float(options["threshold"])
        min_episodes = int(options["min_episodes"])
        rows = low_guest_ratio_podcasts(
            threshold=threshold,
            min_episodes=min_episodes,
        )
        report_path = Path(str(options["report"]))
        write_report(
            rows=rows,
            threshold=threshold,
            min_episodes=min_episodes,
            path=report_path,
        )
        if options["apply"]:
            updated, deactivated = mark_non_interview_podcasts(
                rows=rows,
                threshold=threshold,
                min_episodes=min_episodes,
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Marked {updated} podcasts as non-interview and deactivated "
                    f"{deactivated} feeds. Report: {report_path}"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Found {len(rows)} low-guest-ratio podcasts. Report: {report_path}"
                )
            )


def low_guest_ratio_podcasts(
    *,
    threshold: float,
    min_episodes: int,
) -> list[PodcastClassification]:
    podcasts = (
        Podcast.objects.annotate(
            episode_count=Count("episodes", distinct=True),
            guest_episode_count=Count(
                "episodes",
                filter=Q(episodes__appearances__role="guest"),
                distinct=True,
            ),
        )
        .filter(episode_count__gte=min_episodes)
        .order_by("name")
    )
    rows = []
    for podcast in podcasts:
        ratio = podcast.guest_episode_count / podcast.episode_count
        if ratio < threshold:
            rows.append(
                PodcastClassification(
                    podcast=podcast,
                    episode_count=podcast.episode_count,
                    guest_episode_count=podcast.guest_episode_count,
                    guest_episode_ratio=ratio,
                )
            )
    return sorted(rows, key=lambda row: (row.guest_episode_ratio, row.podcast.name))


def mark_non_interview_podcasts(
    *,
    rows: list[PodcastClassification],
    threshold: float,
    min_episodes: int,
) -> tuple[int, int]:
    updated = 0
    podcast_ids = []
    for row in rows:
        podcast = row.podcast
        metadata = dict(podcast.metadata)
        policy = dict(metadata.get("extraction_policy") or {})
        policy.update(
            {
                "skip_guest_extraction": True,
                "skip_scraping": True,
                "classification": "non_interview",
                "reason": "low_guest_episode_ratio",
                "guest_episode_ratio": row.guest_episode_ratio,
                "guest_episode_count": row.guest_episode_count,
                "episode_count": row.episode_count,
                "threshold": threshold,
                "min_episodes": min_episodes,
            }
        )
        metadata["extraction_policy"] = policy
        podcast.metadata = metadata
        podcast.save(update_fields=["metadata", "updated_at"])
        updated += 1
        podcast_ids.append(podcast.id)
    deactivated = Feed.objects.filter(podcast_id__in=podcast_ids, active=True).update(
        active=False
    )
    return updated, deactivated


def write_report(
    *,
    rows: list[PodcastClassification],
    threshold: float,
    min_episodes: int,
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Non-Interview Podcast Candidates",
        "",
        f"Threshold: guest episode ratio < {threshold:.2%}",
        f"Minimum episodes: {min_episodes}",
        f"Matches: {len(rows)}",
        "",
        "| Podcast ID | Podcast | Episodes | Guest Episodes | Ratio |",
        "|---:|---|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row.podcast.id} | {row.podcast.name} | {row.episode_count} | "
            f"{row.guest_episode_count} | {row.guest_episode_ratio:.2%} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
