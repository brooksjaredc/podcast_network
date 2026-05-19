from datetime import datetime

from django.core.management import call_command
from django.utils import timezone

from podcast_network.network_evolution import calculate_network_evolution
from podcast_network.web.catalog.models import (
    Appearance,
    Episode,
    NetworkEvolutionRun,
    NetworkEvolutionSnapshot,
    Person,
    PersonNetworkEvolutionMetric,
    Podcast,
)


def test_network_evolution_requires_bootstrap_for_initial_backfill() -> None:
    create_evolution_graph()

    stats = calculate_network_evolution()

    assert stats.run.status == NetworkEvolutionRun.Status.SKIPPED
    assert NetworkEvolutionSnapshot.objects.count() == 0


def test_network_evolution_bootstrap_creates_weekly_snapshots() -> None:
    create_evolution_graph()

    stats = calculate_network_evolution(bootstrap=True, max_weeks=2)

    assert stats.run.status == NetworkEvolutionRun.Status.SUCCEEDED
    assert stats.weeks_requested == 2
    assert stats.weeks_calculated == 2
    snapshots = list(NetworkEvolutionSnapshot.objects.order_by("week_start"))
    assert len(snapshots) == 2
    assert snapshots[0].person_nodes == 2
    assert snapshots[0].person_edges == 1
    assert snapshots[0].podcast_count == 1
    assert snapshots[0].episode_count == 1
    assert snapshots[0].guest_appearance_count == 1
    assert snapshots[0].new_person_count == 2
    assert snapshots[0].new_person_edge_count == 1
    assert snapshots[0].new_podcast_count == 1
    metrics = list(PersonNetworkEvolutionMetric.objects.filter(snapshot=snapshots[0]))
    assert len(metrics) == 2
    guest_metric = next(metric for metric in metrics if metric.display_name == "Guest One")
    assert guest_metric.guest_appearances == 1
    assert guest_metric.host_appearances == 0
    assert guest_metric.podcast_count == 1
    assert guest_metric.degree_rank > 0
    assert guest_metric.betweenness_rank > 0


def test_network_evolution_incremental_run_adds_only_new_weeks() -> None:
    create_evolution_graph()
    calculate_network_evolution(bootstrap=True, max_weeks=1)

    stats = calculate_network_evolution(max_weeks=1)

    assert stats.run.status == NetworkEvolutionRun.Status.SUCCEEDED
    assert stats.weeks_requested == 1
    assert NetworkEvolutionSnapshot.objects.count() == 2


def test_network_evolution_reset_only_clears_tables() -> None:
    create_evolution_graph()
    calculate_network_evolution(bootstrap=True, max_weeks=1)

    call_command("calculate_network_evolution", reset_only=True)

    assert NetworkEvolutionRun.objects.count() == 0
    assert NetworkEvolutionSnapshot.objects.count() == 0
    assert PersonNetworkEvolutionMetric.objects.count() == 0


def create_evolution_graph() -> None:
    podcast = Podcast.objects.create(name="Evolution Show")
    host = Person.objects.create(name="Host One", normalized_name="host one")
    guest = Person.objects.create(name="Guest One", normalized_name="guest one")
    for index, published_at in enumerate(
        [
            timezone.make_aware(datetime(2024, 1, 3, 12, 0)),
            timezone.make_aware(datetime(2024, 1, 10, 12, 0)),
        ]
    ):
        episode = Episode.objects.create(
            podcast=podcast,
            guid=f"evolution-{index}",
            title=f"Evolution Episode {index}",
            published_at=published_at,
        )
        Appearance.objects.create(
            episode=episode,
            person=host,
            role=Appearance.Role.HOST,
        )
        Appearance.objects.create(
            episode=episode,
            person=guest,
            role=Appearance.Role.GUEST,
        )
    call_command("sync_person_entities")
