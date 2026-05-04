from __future__ import annotations

import csv
import random
import re
from dataclasses import dataclass
from pathlib import Path

from django.core.management.base import BaseCommand, CommandParser
from django.db.models import Count, Q

from podcast_network.extraction.prompt import build_episode_prompt
from podcast_network.web.catalog.models import Episode


@dataclass(frozen=True)
class SampleRow:
    bucket: str
    episode_id: int
    podcast: str
    title: str
    published_at: str
    description_excerpt: str
    prompt_chars: int
    expected_guests: str = ""
    notes: str = ""


class Command(BaseCommand):
    help = "Generate a diverse CSV sample for guest-extraction prompt testing."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--csv",
            dest="csv_path",
            default="data/reports/guest_extraction_prompt_sample.csv",
        )
        parser.add_argument("--per-bucket", type=int, default=5)
        parser.add_argument("--seed", type=int, default=42)

    def handle(self, *args: object, **options: object) -> None:
        rows = build_sample(per_bucket=int(options["per_bucket"]), seed=int(options["seed"]))
        path = Path(str(options["csv_path"]))
        write_csv(rows, path)
        self.stdout.write(self.style.SUCCESS(f"Wrote {len(rows)} sample episodes to {path}"))


def build_sample(*, per_bucket: int, seed: int) -> list[SampleRow]:
    rng = random.Random(seed)
    rows: list[SampleRow] = []
    seen: set[int] = set()
    buckets = {
        "explicit_with_title": Episode.objects.filter(title__iregex=r"\b(with|w/|featuring)\b"),
        "guest_language_description": Episode.objects.filter(
            description__iregex=r"\b(guest|joined by|talks? with|interview)\b"
        ),
        "possible_topic_confusion": Episode.objects.filter(
            Q(title__iregex=r"\b(on|about|case for|against|death of|life of)\b")
            | Q(description__iregex=r"\b(discuss|discussion|debate|topic|story of)\b")
        ),
        "likely_solo_or_recap": Episode.objects.filter(
            Q(title__iregex=r"\b(solo|monologue|recap|mailbag|bonus|trailer)\b")
            | Q(description__iregex=r"\b(solo|monologue|recap|mailbag|bonus|trailer)\b")
        ),
        "multi_guest_or_panel": Episode.objects.filter(
            Q(title__iregex=r"\b(and|&|panel|roundtable)\b")
            | Q(description__iregex=r"\b(panel|roundtable|joined by|guests)\b")
        ),
        "short_metadata": Episode.objects.annotate(
            description_length=Count("description")
        ).filter(description__exact=""),
        "recent_large_podcasts": Episode.objects.filter(published_at__isnull=False),
        "older_archive": Episode.objects.filter(published_at__year__lt=2016),
    }
    for bucket, queryset in buckets.items():
        for episode in choose_diverse(queryset, per_bucket=per_bucket, rng=rng, seen=seen):
            rows.append(sample_row(bucket, episode))
            seen.add(episode.id)
    return rows


def choose_diverse(
    queryset,
    *,
    per_bucket: int,
    rng: random.Random,
    seen: set[int],
) -> list[Episode]:
    episodes = list(
        queryset.select_related("podcast")
        .exclude(id__in=seen)
        .order_by("podcast__name", "-published_at")
        .values_list("id", "podcast__name")
    )
    rng.shuffle(episodes)
    chosen_ids = []
    chosen_podcasts = set()
    for episode_id, podcast_name in episodes:
        if podcast_name in chosen_podcasts:
            continue
        chosen_ids.append(episode_id)
        chosen_podcasts.add(podcast_name)
        if len(chosen_ids) >= per_bucket:
            break
    if len(chosen_ids) < per_bucket:
        for episode_id, _ in episodes:
            if episode_id not in chosen_ids:
                chosen_ids.append(episode_id)
            if len(chosen_ids) >= per_bucket:
                break
    return list(Episode.objects.select_related("podcast").filter(id__in=chosen_ids))


def sample_row(bucket: str, episode: Episode) -> SampleRow:
    prompt = build_episode_prompt(episode)
    return SampleRow(
        bucket=bucket,
        episode_id=episode.id,
        podcast=episode.podcast.name,
        title=episode.title,
        published_at=episode.published_at.isoformat() if episode.published_at else "",
        description_excerpt=excerpt(episode.description),
        prompt_chars=len(prompt.instructions) + len(prompt.input_text),
    )


def excerpt(value: str, max_chars: int = 420) -> str:
    compact = re.sub(r"\s+", " ", value).strip()
    if len(compact) <= max_chars:
        return compact
    return compact[:max_chars].rsplit(" ", 1)[0] + "..."


def write_csv(rows: list[SampleRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(SampleRow.__annotations__))
        writer.writeheader()
        for row in rows:
            writer.writerow(row.__dict__)
