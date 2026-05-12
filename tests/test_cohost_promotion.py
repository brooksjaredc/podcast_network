from django.utils import timezone

from podcast_network.web.catalog.management.commands.promote_frequent_guests_to_cohosts import (
    DERIVED_COHOST_SOURCE,
    promote_frequent_guests_to_cohosts,
)
from podcast_network.web.catalog.models import Appearance, Episode, Person, Podcast


def test_promotes_guests_over_episode_share_threshold() -> None:
    podcast = Podcast.objects.create(name="Small Regular Show")
    regular = Person.objects.create(name="Small Show Regular", normalized_name="small show regular")
    for index in range(10):
        episode = Episode.objects.create(
            podcast=podcast,
            guid=f"small-regular-promotion-{index}",
            title=f"Episode {index}",
            published_at=timezone.now(),
        )
        if index < 3:
            Appearance.objects.create(
                episode=episode,
                person=regular,
                role=Appearance.Role.GUEST,
                source="test",
            )

    stats = promote_frequent_guests_to_cohosts()

    assert stats.pairs_promoted == 1
    assert stats.host_appearances_created == 3
    assert stats.guest_appearances_deleted == 3
    assert not Appearance.objects.filter(person=regular, role=Appearance.Role.GUEST).exists()
    assert (
        Appearance.objects.filter(
            person=regular,
            role=Appearance.Role.HOST,
            source=DERIVED_COHOST_SOURCE,
        ).count()
        == 3
    )


def test_does_not_promote_guests_at_exact_episode_share_threshold() -> None:
    podcast = Podcast.objects.create(name="Exact Threshold Show")
    regular = Person.objects.create(
        name="Exact Threshold Regular",
        normalized_name="exact threshold regular",
    )
    for index in range(10):
        episode = Episode.objects.create(
            podcast=podcast,
            guid=f"exact-threshold-promotion-{index}",
            title=f"Episode {index}",
            published_at=timezone.now(),
        )
        if index < 2:
            Appearance.objects.create(
                episode=episode,
                person=regular,
                role=Appearance.Role.GUEST,
                source="test",
            )

    stats = promote_frequent_guests_to_cohosts()

    assert stats.pairs_promoted == 0
    assert Appearance.objects.filter(person=regular, role=Appearance.Role.GUEST).count() == 2
