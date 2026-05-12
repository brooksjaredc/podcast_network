from __future__ import annotations

from django.core.management import call_command
from django.test import TestCase

from podcast_network.entity_resolution import (
    canonical_person_id,
    person_observation_id,
    person_record_id,
)
from podcast_network.web.catalog.models import (
    Appearance,
    CanonicalPersonEntity,
    Episode,
    Person,
    PersonEntityCandidatePair,
    PersonEntityLink,
    PersonObservation,
    Podcast,
)
from podcast_network.web.explorer.services import database_six_degrees_graph


class PersonEntityResolutionTests(TestCase):
    def test_stable_ids_are_deterministic(self) -> None:
        record_id = person_record_id(episode_id=12, normalized_name="jane doe")

        assert record_id == person_record_id(episode_id=12, normalized_name="jane doe")
        assert record_id != person_record_id(episode_id=13, normalized_name="jane doe")
        assert person_observation_id(
            provider="appearance",
            record_id=record_id,
            role="guest",
        ) == person_observation_id(provider="appearance", record_id=record_id, role="guest")
        assert canonical_person_id("jane doe").startswith("person_")

    def test_sync_person_entities_builds_observations_canonicals_and_links(self) -> None:
        podcast = Podcast.objects.create(name="Example Show")
        episode = Episode.objects.create(
            podcast=podcast,
            guid="episode-1",
            title="Episode 1",
        )
        jane = Person.objects.create(name="Jane Doe", normalized_name="jane doe")
        Appearance.objects.create(
            episode=episode,
            person=jane,
            role=Appearance.Role.GUEST,
            source="llm-guest-extraction",
            confidence=0.95,
        )

        call_command("sync_person_entities")

        observation = PersonObservation.objects.get()
        assert observation.observed_name == "Jane Doe"
        assert observation.normalized_name == "jane doe"
        assert observation.role == Appearance.Role.GUEST
        canonical = CanonicalPersonEntity.objects.get()
        assert canonical.am_entity_id == canonical_person_id("jane doe")
        assert canonical.display_name == "Jane Doe"
        assert canonical.aliases == ["Jane Doe"]
        assert canonical.roles == [Appearance.Role.GUEST]
        link = PersonEntityLink.objects.get()
        assert link.observation == observation
        assert link.canonical == canonical
        assert link.match_method == "exact_normalized_name"
        assert link.match_probability == 1.0

    def test_sync_person_entities_is_idempotent(self) -> None:
        podcast = Podcast.objects.create(name="Example Show")
        episode = Episode.objects.create(
            podcast=podcast,
            guid="episode-1",
            title="Episode 1",
        )
        jane = Person.objects.create(name="Jane Doe", normalized_name="jane doe")
        Appearance.objects.create(
            episode=episode,
            person=jane,
            role=Appearance.Role.GUEST,
        )

        call_command("sync_person_entities")
        call_command("sync_person_entities")

        assert PersonObservation.objects.count() == 1
        assert CanonicalPersonEntity.objects.count() == 1
        assert PersonEntityLink.objects.count() == 1

    def test_apply_person_entity_matches_relinks_observations_and_survives_resync(self) -> None:
        podcast = Podcast.objects.create(name="Example Show")
        episode = Episode.objects.create(podcast=podcast, guid="episode-1", title="Episode 1")
        tim = Person.objects.create(name="Tim Andrews", normalized_name="tim andrews")
        tim_long = Person.objects.create(
            name="Tim Andrews Here",
            normalized_name="tim andrews here",
        )
        Appearance.objects.create(episode=episode, person=tim, role=Appearance.Role.GUEST)
        Appearance.objects.create(episode=episode, person=tim_long, role=Appearance.Role.GUEST)
        call_command("sync_person_entities")
        call_command("generate_person_entity_candidates", "--min-observations", "1")
        pair = PersonEntityCandidatePair.objects.get()
        pair.model_name = "person-entity-xgboost-namefreq-groups-v1"
        pair.match_probability = 0.99
        pair.save(update_fields=["model_name", "match_probability", "updated_at"])

        call_command("apply_person_entity_matches")

        target = CanonicalPersonEntity.objects.get(normalized_name="tim andrews here")
        assert PersonEntityLink.objects.filter(canonical=target).count() == 2
        assert PersonEntityLink.objects.filter(
            canonical=target,
            match_method="ml_entity_resolution:person-entity-xgboost-namefreq-groups-v1",
        ).count() == 1

        call_command("sync_person_entities")

        assert PersonEntityLink.objects.filter(canonical=target).count() == 2

    def test_database_graph_uses_canonical_person_links_when_available(self) -> None:
        podcast = Podcast.objects.create(name="Example Show")
        episode = Episode.objects.create(podcast=podcast, guid="episode-1", title="Episode 1")
        tim = Person.objects.create(name="Tim Andrews", normalized_name="tim andrews")
        tim_long = Person.objects.create(
            name="Tim Andrews Here",
            normalized_name="tim andrews here",
        )
        Appearance.objects.create(episode=episode, person=tim, role=Appearance.Role.GUEST)
        Appearance.objects.create(episode=episode, person=tim_long, role=Appearance.Role.GUEST)
        call_command("sync_person_entities")
        call_command("generate_person_entity_candidates", "--min-observations", "1")
        pair = PersonEntityCandidatePair.objects.get()
        pair.model_name = "person-entity-xgboost-namefreq-groups-v1"
        pair.match_probability = 0.99
        pair.save(update_fields=["model_name", "match_probability", "updated_at"])
        call_command("apply_person_entity_matches")
        database_six_degrees_graph.cache_clear()

        graph = database_six_degrees_graph()

        assert "Tim Andrews Here" in graph.names
        assert "Tim Andrews" not in graph.names

    def test_known_person_aliases_can_be_scoped_by_podcast(self) -> None:
        startalk = Podcast.objects.create(name="StarTalk Radio")
        other_show = Podcast.objects.create(name="Other Science Show")
        startalk_episode = Episode.objects.create(
            podcast=startalk,
            guid="startalk-1",
            title="Episode 1",
        )
        other_episode = Episode.objects.create(
            podcast=other_show,
            guid="other-science-1",
            title="Episode 1",
        )
        neil_full = Person.objects.create(
            name="Neil deGrasse Tyson",
            normalized_name="neil degrasse tyson",
        )
        neil_short = Person.objects.create(name="Neil Tyson", normalized_name="neil tyson")
        Appearance.objects.create(
            episode=startalk_episode,
            person=neil_full,
            role=Appearance.Role.HOST,
        )
        Appearance.objects.create(
            episode=startalk_episode,
            person=neil_short,
            role=Appearance.Role.GUEST,
        )
        Appearance.objects.create(
            episode=other_episode,
            person=neil_short,
            role=Appearance.Role.GUEST,
        )

        call_command("sync_person_entities")
        call_command("apply_known_person_entity_aliases")

        target = CanonicalPersonEntity.objects.get(normalized_name="neil degrasse tyson")
        assert PersonEntityLink.objects.filter(
            observation__podcast=startalk,
            observation__person=neil_short,
            canonical=target,
            match_method="known_person_alias",
        ).exists()
        assert PersonEntityLink.objects.filter(
            observation__podcast=other_show,
            observation__person=neil_short,
            canonical__normalized_name="neil tyson",
        ).exists()

    def test_known_person_aliases_merge_global_and_podcast_specific_aliases(self) -> None:
        startalk = Podcast.objects.create(name="StarTalk Radio")
        von = Podcast.objects.create(name="The Von Haessler Doctrine")
        science_episode = Episode.objects.create(
            podcast=startalk,
            guid="science-guy-1",
            title="Episode 1",
        )
        von_episode = Episode.objects.create(
            podcast=von,
            guid="dr-joe-1",
            title="Episode 1",
        )
        bill = Person.objects.create(name="Bill Nye", normalized_name="bill nye")
        bill_long = Person.objects.create(
            name="Bill Nye the Science Guy",
            normalized_name="bill nye the science guy",
        )
        dr_joe = Person.objects.create(name="Dr Joe", normalized_name="dr joe")
        dr_joe_full = Person.objects.create(
            name="Dr Joe Esposito",
            normalized_name="dr joe esposito",
        )
        for person in [bill, bill_long]:
            Appearance.objects.create(episode=science_episode, person=person, role="guest")
        for person in [dr_joe, dr_joe_full]:
            Appearance.objects.create(episode=von_episode, person=person, role="guest")

        call_command("sync_person_entities")
        call_command("apply_known_person_entity_aliases")

        assert PersonEntityLink.objects.filter(
            observation__person=bill_long,
            canonical__normalized_name="bill nye",
            match_method="known_person_alias",
        ).exists()
        assert PersonEntityLink.objects.filter(
            observation__person=dr_joe,
            canonical__normalized_name="dr joe esposito",
            match_method="known_person_alias",
        ).exists()
