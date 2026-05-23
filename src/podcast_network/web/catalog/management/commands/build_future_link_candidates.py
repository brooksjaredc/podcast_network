from __future__ import annotations

from datetime import datetime

from django.core.management.base import BaseCommand, CommandParser
from django.utils import timezone

from podcast_network.future_link_prediction import (
    build_degree_limited_link_candidates,
    build_shared_guest_heuristic_link_candidates,
    compare_candidate_sets,
    format_candidate_set_comparison,
    format_link_candidate_stats,
    format_podcast_eligibility_stats,
    latest_cutoff_for_labeling,
    podcast_eligibility_stats,
)


class Command(BaseCommand):
    help = "Prototype future podcast-guest link candidate generation for one cutoff."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--cutoff",
            type=parse_datetime,
            help=(
                "Cutoff datetime in ISO format. Defaults to latest linked episode date minus "
                "--horizon-days."
            ),
        )
        parser.add_argument("--horizon-days", type=int, default=90)
        parser.add_argument(
            "--max-degree",
            type=int,
            default=3,
            help="Maximum bipartite graph distance from podcast to candidate guest.",
        )
        parser.add_argument(
            "--include-inactive-podcasts",
            action="store_true",
            help="Score inactive podcasts too.",
        )
        parser.add_argument(
            "--include-hosts",
            action="store_true",
            help="Allow people who have hosted the target podcast as candidates.",
        )
        parser.add_argument(
            "--min-podcast-guest-count",
            type=int,
            default=1,
            help="Minimum historical unique guest links before scoring a podcast.",
        )
        parser.add_argument(
            "--strategy",
            choices=["degree", "shared-guest"],
            default="degree",
            help="Candidate retrieval strategy.",
        )
        parser.add_argument(
            "--min-shared-guests",
            type=int,
            default=1,
            help=(
                "For shared-guest strategy, require this many shared guests with a "
                "neighbor podcast."
            ),
        )
        parser.add_argument(
            "--top-per-podcast",
            type=int,
            default=5000,
            help=(
                "For shared-guest strategy, keep this many highest-scored candidates per podcast. "
                "Use 0 for no cap."
            ),
        )
        parser.add_argument(
            "--always-keep-score",
            type=int,
            default=0,
            help=(
                "For shared-guest strategy, keep candidates with at least this retrieval score "
                "even when they fall outside --top-per-podcast."
            ),
        )
        parser.add_argument(
            "--compare-degree-baseline",
            action="store_true",
            help="Also build the degree-limited set and report heuristic positive loss.",
        )
        parser.add_argument(
            "--show-podcast-eligibility",
            action="store_true",
            help="Print why some podcasts are not scored.",
        )

    def handle(self, *args: object, **options: object) -> None:
        cutoff_at = options["cutoff"]
        horizon_days = int(options["horizon_days"])
        if cutoff_at is None:
            cutoff_at = latest_cutoff_for_labeling(horizon_days=horizon_days)
        if cutoff_at is None:
            self.stdout.write(
                self.style.WARNING(
                    "No linked episode dates found. Run guest/entity sync before building "
                    "future-link candidates."
                )
            )
            return

        active_podcasts_only = not bool(options["include_inactive_podcasts"])
        exclude_hosts = not bool(options["include_hosts"])
        min_podcast_guest_count = int(options["min_podcast_guest_count"])

        if options["show_podcast_eligibility"]:
            eligibility = podcast_eligibility_stats(
                cutoff_at=cutoff_at,
                active_only=active_podcasts_only,
                min_guest_count=min_podcast_guest_count,
            )
            for line in format_podcast_eligibility_stats(eligibility):
                self.stdout.write(line)

        if options["strategy"] == "shared-guest":
            result = build_shared_guest_heuristic_link_candidates(
                cutoff_at=cutoff_at,
                horizon_days=horizon_days,
                active_podcasts_only=active_podcasts_only,
                exclude_hosts=exclude_hosts,
                min_podcast_guest_count=min_podcast_guest_count,
                min_shared_guests=int(options["min_shared_guests"]),
                top_per_podcast=int(options["top_per_podcast"]),
                always_keep_score=int(options["always_keep_score"]),
            )
        else:
            result = build_degree_limited_link_candidates(
                cutoff_at=cutoff_at,
                horizon_days=horizon_days,
                max_degree=int(options["max_degree"]),
                active_podcasts_only=active_podcasts_only,
                exclude_hosts=exclude_hosts,
                min_podcast_guest_count=min_podcast_guest_count,
            )
        for line in format_link_candidate_stats(result.stats):
            self.stdout.write(line)

        if options["strategy"] == "shared-guest" and options["compare_degree_baseline"]:
            baseline = build_degree_limited_link_candidates(
                cutoff_at=cutoff_at,
                horizon_days=horizon_days,
                max_degree=int(options["max_degree"]),
                active_podcasts_only=active_podcasts_only,
                exclude_hosts=exclude_hosts,
                min_podcast_guest_count=min_podcast_guest_count,
            )
            comparison = compare_candidate_sets(baseline=baseline, heuristic=result)
            for line in format_candidate_set_comparison(comparison):
                self.stdout.write(line)


def parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed
