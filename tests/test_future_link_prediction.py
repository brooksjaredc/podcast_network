from datetime import datetime, timedelta

from django.core.management import call_command
from django.utils import timezone

from podcast_network.future_links.prediction import (
    build_degree_limited_link_candidates,
    build_historical_link_data,
    build_shared_guest_heuristic_link_candidates,
    compare_candidate_sets,
    podcast_eligibility_stats,
)
from podcast_network.web.catalog.models import (
    Appearance,
    Episode,
    Person,
    PersonEntityLink,
    Podcast,
)


def test_degree_limited_candidates_retrieve_near_future_links() -> None:
    cutoff_at = timezone.make_aware(datetime(2025, 1, 1, 0, 0))
    create_link_prediction_graph(cutoff_at=cutoff_at)

    result = build_degree_limited_link_candidates(
        cutoff_at=cutoff_at,
        horizon_days=90,
        max_degree=3,
    )

    assert result.stats.candidate_count == 2
    assert result.stats.positive_count == 2
    assert result.stats.negative_count == 0
    assert result.stats.future_positive_count == 6
    assert result.stats.positives_excluded_existing_link == 1
    assert result.stats.positives_excluded_host == 1
    assert result.stats.positives_missed_by_retrieval == 2
    assert result.stats.distance_counts == {3: 2}
    assert result.stats.distance_positive_counts == {3: 2}


def test_degree_limit_controls_candidate_volume_and_recall() -> None:
    cutoff_at = timezone.make_aware(datetime(2025, 1, 1, 0, 0))
    create_link_prediction_graph(cutoff_at=cutoff_at)

    result = build_degree_limited_link_candidates(
        cutoff_at=cutoff_at,
        horizon_days=90,
        max_degree=1,
    )

    assert result.stats.candidate_count == 0
    assert result.stats.positive_count == 0
    assert result.stats.positives_missed_by_retrieval == 4


def test_shared_guest_heuristic_matches_degree_three_without_cap() -> None:
    cutoff_at = timezone.make_aware(datetime(2025, 1, 1, 0, 0))
    create_link_prediction_graph(cutoff_at=cutoff_at)

    baseline = build_degree_limited_link_candidates(
        cutoff_at=cutoff_at,
        horizon_days=90,
        max_degree=3,
    )
    heuristic = build_shared_guest_heuristic_link_candidates(
        cutoff_at=cutoff_at,
        horizon_days=90,
        top_per_podcast=0,
    )
    comparison = compare_candidate_sets(baseline=baseline, heuristic=heuristic)

    assert heuristic.stats.candidate_count == 2
    assert heuristic.stats.positive_count == 2
    assert comparison.positives_lost_from_baseline == 0
    assert comparison.positive_retention == 1.0


def test_shared_guest_heuristic_can_keep_strong_candidates_outside_top_cap() -> None:
    cutoff_at = timezone.make_aware(datetime(2025, 1, 1, 0, 0))
    create_link_prediction_graph(cutoff_at=cutoff_at)

    result = build_shared_guest_heuristic_link_candidates(
        cutoff_at=cutoff_at,
        horizon_days=90,
        top_per_podcast=1,
        always_keep_score=1,
    )

    assert result.stats.candidate_count == 2
    assert result.stats.positive_count == 2


def test_podcast_eligibility_stats_explain_scored_podcast_count() -> None:
    cutoff_at = timezone.make_aware(datetime(2025, 1, 1, 0, 0))
    create_link_prediction_graph(cutoff_at=cutoff_at)

    stats = podcast_eligibility_stats(cutoff_at=cutoff_at)

    assert stats.total_podcasts == 3
    assert stats.active_podcasts == 3
    assert stats.active_historical_linked_podcasts == 3
    assert stats.scored_podcasts == 3


def test_historical_link_data_can_filter_by_pickup_time() -> None:
    cutoff_at = timezone.make_aware(datetime(2025, 1, 1, 0, 0))
    create_link_prediction_graph(cutoff_at=cutoff_at)
    PersonEntityLink.objects.update(created_at=cutoff_at + timedelta(hours=1))

    unfiltered = build_historical_link_data(cutoff_at=cutoff_at)
    filtered = build_historical_link_data(
        cutoff_at=cutoff_at,
        link_created_before=cutoff_at,
    )

    assert len(unfiltered.existing_guest_links) == 5
    assert len(unfiltered.host_links) == 3
    assert filtered.existing_guest_links == set()
    assert filtered.host_links == set()


def create_link_prediction_graph(*, cutoff_at: datetime) -> None:
    podcast_a = Podcast.objects.create(name="Podcast A")
    podcast_b = Podcast.objects.create(name="Podcast B")
    podcast_c = Podcast.objects.create(name="Podcast C")
    people = {
        name: Person.objects.create(name=name, normalized_name=name.lower())
        for name in [
            "Host A",
            "Host B",
            "Host C",
            "Guest One",
            "Guest Two",
            "Guest Three",
            "Guest Four",
        ]
    }

    before = cutoff_at - timedelta(days=30)
    add_episode(
        podcast=podcast_a,
        guid="a-before",
        published_at=before,
        hosts=[people["Host A"]],
        guests=[people["Guest One"], people["Guest Two"]],
    )
    add_episode(
        podcast=podcast_b,
        guid="b-before",
        published_at=before,
        hosts=[people["Host B"]],
        guests=[people["Guest One"], people["Guest Three"]],
    )
    add_episode(
        podcast=podcast_c,
        guid="c-before",
        published_at=before,
        hosts=[people["Host C"]],
        guests=[people["Guest Four"]],
    )

    future = cutoff_at + timedelta(days=10)
    add_episode(
        podcast=podcast_a,
        guid="a-near-positive",
        published_at=future,
        hosts=[people["Host A"]],
        guests=[people["Guest Three"]],
    )
    add_episode(
        podcast=podcast_b,
        guid="b-near-positive",
        published_at=future,
        hosts=[people["Host B"]],
        guests=[people["Guest Two"]],
    )
    add_episode(
        podcast=podcast_a,
        guid="a-far-positive",
        published_at=future,
        hosts=[people["Host A"]],
        guests=[people["Guest Four"]],
    )
    add_episode(
        podcast=podcast_c,
        guid="c-far-positive",
        published_at=future,
        hosts=[people["Host C"]],
        guests=[people["Guest One"]],
    )
    add_episode(
        podcast=podcast_a,
        guid="a-repeat-positive",
        published_at=future,
        hosts=[people["Host A"]],
        guests=[people["Guest One"]],
    )
    add_episode(
        podcast=podcast_a,
        guid="a-host-positive",
        published_at=future,
        hosts=[people["Host A"]],
        guests=[people["Host A"]],
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
