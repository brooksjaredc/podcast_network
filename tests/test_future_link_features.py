from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from django.core.management import call_command
from django.utils import timezone

from podcast_network.future_links.features import (
    build_balanced_experiment_dataset,
    build_feature_context,
    build_full_feature_matrix,
)
from podcast_network.future_links.prediction import build_historical_link_data
from podcast_network.web.catalog.models import (
    Appearance,
    Episode,
    Person,
    PersonEntityLink,
    Podcast,
)


def test_build_balanced_experiment_dataset_keeps_positives_and_samples_negatives(
    tmp_path: Path,
) -> None:
    cutoff_at = timezone.make_aware(datetime(2025, 1, 1, 0, 0))
    create_feature_graph(cutoff_at=cutoff_at)
    output_path = tmp_path / "future_link_features.csv"

    stats = build_balanced_experiment_dataset(
        output_path=output_path,
        cutoff_at=cutoff_at,
        horizon_days=90,
        max_degree=3,
        negative_ratio=1,
        sample_seed="test",
    )

    frame = pd.read_csv(output_path)
    assert stats.positive_count == 1
    assert stats.sampled_negative_count == 1
    assert len(frame) == 2
    assert set(frame["label"]) == {0, 1}
    assert "shared_neighbor_score" in frame.columns
    assert "guest_momentum_90_365" in frame.columns
    assert set(frame["split"]) <= {"train", "test"}


def test_build_full_feature_matrix_writes_numpy_arrays(tmp_path: Path) -> None:
    cutoff_at = timezone.make_aware(datetime(2025, 1, 1, 0, 0))
    create_feature_graph(cutoff_at=cutoff_at)
    output_dir = tmp_path / "matrix"

    stats = build_full_feature_matrix(
        output_dir=output_dir,
        cutoff_at=cutoff_at,
        horizon_days=90,
        max_degree=3,
    )

    assert stats.row_count == 3
    assert stats.positive_count == 1
    assert (output_dir / "X.npy").exists()
    assert (output_dir / "y.npy").exists()
    assert (output_dir / "split.npy").exists()
    assert (output_dir / "metadata.json").exists()


def test_feature_context_can_filter_by_pickup_time() -> None:
    cutoff_at = timezone.make_aware(datetime(2025, 1, 1, 0, 0))
    create_feature_graph(cutoff_at=cutoff_at)
    PersonEntityLink.objects.update(created_at=cutoff_at + timedelta(hours=1))
    historical = build_historical_link_data(cutoff_at=cutoff_at)

    unfiltered = build_feature_context(cutoff_at=cutoff_at, historical=historical)
    filtered = build_feature_context(
        cutoff_at=cutoff_at,
        historical=historical,
        link_created_before=cutoff_at,
    )

    assert sum(unfiltered.guest_appearance_counts.values()) == 5
    assert sum(filtered.guest_appearance_counts.values()) == 0


def create_feature_graph(*, cutoff_at: datetime) -> None:
    podcast_a = Podcast.objects.create(name="Feature Podcast A")
    podcast_b = Podcast.objects.create(name="Feature Podcast B")
    people = {
        name: Person.objects.create(name=name, normalized_name=name.lower())
        for name in [
            "Host A",
            "Host B",
            "Guest One",
            "Guest Two",
            "Positive Guest",
            "Negative Guest",
        ]
    }
    before = cutoff_at - timedelta(days=30)
    add_episode(
        podcast=podcast_a,
        guid="feature-a-before",
        published_at=before,
        hosts=[people["Host A"]],
        guests=[people["Guest One"], people["Guest Two"]],
    )
    add_episode(
        podcast=podcast_b,
        guid="feature-b-before",
        published_at=before,
        hosts=[people["Host B"]],
        guests=[people["Guest One"], people["Positive Guest"], people["Negative Guest"]],
    )
    add_episode(
        podcast=podcast_a,
        guid="feature-a-future",
        published_at=cutoff_at + timedelta(days=10),
        hosts=[people["Host A"]],
        guests=[people["Positive Guest"]],
    )
    call_command("sync_person_entities")


def add_episode(
    *,
    podcast: Podcast,
    guid: str,
    published_at: datetime,
    hosts: list[Person],
    guests: list[Person],
) -> Episode:
    episode = Episode.objects.create(
        podcast=podcast,
        guid=guid,
        title=guid,
        published_at=published_at,
    )
    for host in hosts:
        Appearance.objects.create(episode=episode, person=host, role=Appearance.Role.HOST)
    for guest in guests:
        Appearance.objects.create(episode=episode, person=guest, role=Appearance.Role.GUEST)
    return episode
