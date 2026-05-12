from __future__ import annotations

from django.core.management import call_command
from django.test import TestCase

from podcast_network.network_metrics import calculate_and_store_network_metrics
from podcast_network.web.catalog.models import (
    Appearance,
    Episode,
    NetworkMetricRun,
    Person,
    PersonNetworkMetric,
    Podcast,
    PodcastNetworkMetric,
)


class NetworkMetricTests(TestCase):
    def test_calculate_network_metrics_stores_person_and_podcast_snapshots(self) -> None:
        first_podcast = Podcast.objects.create(name="First Show")
        second_podcast = Podcast.objects.create(name="Second Show")
        first_episode = Episode.objects.create(
            podcast=first_podcast,
            guid="first-1",
            title="First episode",
        )
        second_episode = Episode.objects.create(
            podcast=second_podcast,
            guid="second-1",
            title="Second episode",
        )
        host_one = Person.objects.create(name="Host One", normalized_name="host one")
        host_two = Person.objects.create(name="Host Two", normalized_name="host two")
        shared_guest = Person.objects.create(
            name="Shared Guest",
            normalized_name="shared guest",
        )
        Appearance.objects.create(
            episode=first_episode,
            person=host_one,
            role=Appearance.Role.HOST,
        )
        Appearance.objects.create(
            episode=first_episode,
            person=shared_guest,
            role=Appearance.Role.GUEST,
        )
        Appearance.objects.create(
            episode=second_episode,
            person=host_two,
            role=Appearance.Role.HOST,
        )
        Appearance.objects.create(
            episode=second_episode,
            person=shared_guest,
            role=Appearance.Role.GUEST,
        )
        call_command("sync_person_entities")

        run = calculate_and_store_network_metrics()

        assert run.status == NetworkMetricRun.Status.SUCCEEDED
        assert run.person_nodes == 3
        assert run.person_edges == 2
        assert PersonNetworkMetric.objects.filter(run=run).count() == 3
        assert PodcastNetworkMetric.objects.filter(run=run).count() == 2
        shared_metric = PersonNetworkMetric.objects.get(
            run=run,
            display_name="Shared Guest",
        )
        assert shared_metric.hub_rank == 1
        assert shared_metric.guest_appearances == 2
        assert shared_metric.podcast_count == 2
        assert PodcastNetworkMetric.objects.get(
            run=run,
            podcast=first_podcast,
        ).shared_guest_edges == 1
