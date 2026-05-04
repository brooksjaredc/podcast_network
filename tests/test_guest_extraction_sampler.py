from __future__ import annotations

from podcast_network.web.catalog.management.commands.sample_guest_extraction_episodes import (
    build_sample,
)
from podcast_network.web.catalog.models import Episode, Podcast


def test_build_sample_returns_bucketed_rows() -> None:
    podcast = Podcast.objects.create(name="Sampler Podcast")
    Episode.objects.create(
        podcast=podcast,
        guid="with-guest",
        title="Episode with Jane Doe",
        description="Jane Doe joins the show.",
    )
    Episode.objects.create(
        podcast=podcast,
        guid="topic",
        title="About Jane Doe",
        description="A discussion about Jane Doe.",
    )

    rows = build_sample(per_bucket=1, seed=1)

    assert rows
    assert any(row.bucket == "explicit_with_title" for row in rows)
    assert all(row.expected_guests == "" for row in rows)
