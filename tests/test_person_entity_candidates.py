from __future__ import annotations

from django.core.management import call_command
from django.test import TestCase

from podcast_network.entity_features import (
    EntityProfile,
    apply_entity_score_guards,
    cleaned_name_tokens,
    damerau_distance,
    heuristic_person_match_score,
    nickname_stripped_name_tokens,
    person_pair_features,
    profile_for_entity,
    repeated_first_name_suffix_stripped_tokens,
)
from podcast_network.web.catalog.models import (
    Appearance,
    CanonicalPersonEntity,
    Episode,
    Person,
    PersonEntityCandidatePair,
    PersonEntityPairLabel,
    Podcast,
)


class PersonEntityCandidateTests(TestCase):
    def test_cleaned_name_features_strip_titles_and_credentials(self) -> None:
        left = EntityProfile(
            entity_id="left",
            display_name="Dr. Zach Bush",
            normalized_name="dr zach bush",
            tokens=("dr", "zach", "bush"),
            alpha_tokens=("dr", "zach", "bush"),
            observation_count=2,
            roles=("guest",),
            podcast_ids=frozenset({1}),
            genres=frozenset({"health"}),
        )
        right = EntityProfile(
            entity_id="right",
            display_name="Zach Bush, MD",
            normalized_name="zach bush md",
            tokens=("zach", "bush", "md"),
            alpha_tokens=("zach", "bush", "md"),
            observation_count=2,
            roles=("guest",),
            podcast_ids=frozenset({1}),
            genres=frozenset({"health"}),
        )

        features = person_pair_features(left, right)
        score, reasons = heuristic_person_match_score(features)

        assert cleaned_name_tokens("dr zach bush") == ("zach", "bush")
        assert cleaned_name_tokens("zach bush md") == ("zach", "bush")
        assert features["same_cleaned_token_set"] is True
        assert features["cleaned_token_jaccard"] == 1.0
        assert score >= 0.95
        assert "same cleaned token set" in reasons

    def test_nickname_stripped_features_match_quoted_middle_nickname(self) -> None:
        left = EntityProfile(
            entity_id="left",
            display_name="Michael Render",
            normalized_name="michael render",
            tokens=("michael", "render"),
            alpha_tokens=("michael", "render"),
            observation_count=2,
            roles=("guest",),
            podcast_ids=frozenset({1}),
            genres=frozenset({"music"}),
        )
        right = EntityProfile(
            entity_id="right",
            display_name='Michael "Killer Mike" Render',
            normalized_name="michael killer mike render",
            tokens=("michael", "killer", "mike", "render"),
            alpha_tokens=("michael", "killer", "mike", "render"),
            observation_count=2,
            roles=("guest",),
            podcast_ids=frozenset({1}),
            genres=frozenset({"music"}),
        )

        features = person_pair_features(left, right)
        score, reasons = heuristic_person_match_score(features)

        assert nickname_stripped_name_tokens('Michael "Killer Mike" Render') == (
            "michael",
            "render",
        )
        assert features["one_name_has_quoted_nickname"] is True
        assert features["same_nickname_stripped_token_set"] is True
        assert features["nickname_stripped_token_jaccard"] == 1.0
        assert score >= 0.95
        assert "same name after stripping quoted nickname" in reasons

    def test_group_name_features_and_guard_prevent_distinct_group_matches(self) -> None:
        left = EntityProfile(
            entity_id="left",
            display_name="The Lucas Brothers",
            normalized_name="the lucas brothers",
            tokens=("the", "lucas", "brothers"),
            alpha_tokens=("the", "lucas", "brothers"),
            observation_count=2,
            roles=("guest",),
            podcast_ids=frozenset({1}),
            genres=frozenset({"comedy"}),
        )
        right = EntityProfile(
            entity_id="right",
            display_name="The Sklar Brothers",
            normalized_name="the sklar brothers",
            tokens=("the", "sklar", "brothers"),
            alpha_tokens=("the", "sklar", "brothers"),
            observation_count=2,
            roles=("guest",),
            podcast_ids=frozenset({1}),
            genres=frozenset({"comedy"}),
        )

        features = person_pair_features(left, right)
        guarded_score, reasons = apply_entity_score_guards(0.91, features)

        assert features["both_group_names"] is True
        assert features["shared_group_designator"] is True
        assert features["same_group_name_tokens"] is False
        assert guarded_score == 0.2
        assert "distinct group names are not person matches" in reasons

    def test_name_cleanup_features_cover_alias_suffixes_and_typo_edits(self) -> None:
        assert repeated_first_name_suffix_stripped_tokens(("nick", "englishnick")) == (
            "nick",
            "english",
        )
        assert damerau_distance("caiaccio", "caiacio") == 1
        assert damerau_distance("caiaccio", "caiaicio") <= 2

    def test_pair_features_include_string_podcast_genre_and_graph_signals(self) -> None:
        podcast = Podcast.objects.create(
            name="Example Show",
            metadata={"legacy": {"categories": ["Comedy"]}},
        )
        episode = Episode.objects.create(podcast=podcast, guid="episode-1", title="Episode 1")
        tim = Person.objects.create(name="Tim Andrews", normalized_name="tim andrews")
        tim_here = Person.objects.create(
            name="Tim Andrews Here",
            normalized_name="tim andrews here",
        )
        Appearance.objects.create(episode=episode, person=tim, role=Appearance.Role.GUEST)
        Appearance.objects.create(episode=episode, person=tim_here, role=Appearance.Role.GUEST)
        call_command("sync_person_entities")

        left = profile_for_entity(CanonicalPersonEntity.objects.get(normalized_name="tim andrews"))
        right = profile_for_entity(
            CanonicalPersonEntity.objects.get(normalized_name="tim andrews here")
        )

        features = person_pair_features(left, right)

        assert features["token_overlap_count"] == 2
        assert features["one_name_contains_other_tokens"] is True
        assert features["shared_podcast_count"] == 1
        assert features["shared_genre_count"] == 1
        assert features["graph_distance_proxy"] == 2

    def test_generate_candidates_creates_feature_rows(self) -> None:
        podcast = Podcast.objects.create(
            name="Example Show",
            metadata={"legacy": {"categories": ["Comedy"]}},
        )
        episode = Episode.objects.create(podcast=podcast, guid="episode-1", title="Episode 1")
        tim = Person.objects.create(name="Tim Andrews", normalized_name="tim andrews")
        tim_here = Person.objects.create(
            name="Tim Andrews Here",
            normalized_name="tim andrews here",
        )
        Appearance.objects.create(episode=episode, person=tim, role=Appearance.Role.GUEST)
        Appearance.objects.create(episode=episode, person=tim_here, role=Appearance.Role.GUEST)
        call_command("sync_person_entities")

        call_command(
            "generate_person_entity_candidates",
            "--min-observations",
            "1",
            "--limit-pairs",
            "10",
        )

        pair = PersonEntityCandidatePair.objects.get()
        assert {pair.left.normalized_name, pair.right.normalized_name} == {
            "tim andrews",
            "tim andrews here",
        }
        assert "clean-first-two:tim:andrews" in pair.blocking_keys
        assert pair.features["one_name_contains_other_tokens"] is True

    def test_heuristic_score_rewards_shared_context_and_name_overlap(self) -> None:
        score, reasons = heuristic_person_match_score(
            {
                "name_sequence_ratio": 0.92,
                "token_jaccard": 0.75,
                "cleaned_name_sequence_ratio": 0.92,
                "cleaned_token_jaccard": 0.75,
                "same_token_set": False,
                "same_cleaned_token_set": False,
                "one_name_contains_other_tokens": True,
                "same_first_token": True,
                "same_last_token": True,
                "same_cleaned_first_token": True,
                "same_cleaned_last_token": True,
                "shared_podcast_count": 2,
                "genre_jaccard": 0.5,
                "role_jaccard": 1.0,
                "graph_distance_proxy": 2,
                "has_graph_distance_proxy": True,
            }
        )

        assert score >= 0.9
        assert "shared podcast with strong name overlap" in reasons

    def test_heuristic_score_does_not_overreward_shared_podcast_with_weak_name_match(
        self,
    ) -> None:
        score, reasons = heuristic_person_match_score(
            {
                "name_sequence_ratio": 0.45,
                "token_jaccard": 0.33,
                "cleaned_name_sequence_ratio": 0.45,
                "cleaned_token_jaccard": 0.33,
                "same_token_set": False,
                "same_cleaned_token_set": False,
                "one_name_contains_other_tokens": False,
                "same_first_token": True,
                "same_last_token": False,
                "same_cleaned_first_token": True,
                "same_cleaned_last_token": False,
                "shared_podcast_count": 1,
                "genre_jaccard": 1.0,
                "role_jaccard": 1.0,
                "graph_distance_proxy": 2,
                "has_graph_distance_proxy": True,
            }
        )

        assert score < 0.5
        assert "low cleaned-name overlap" in reasons

    def test_score_command_persists_match_probability(self) -> None:
        podcast = Podcast.objects.create(name="Example Show")
        episode = Episode.objects.create(podcast=podcast, guid="episode-1", title="Episode 1")
        tim = Person.objects.create(name="Tim Andrews", normalized_name="tim andrews")
        tim_here = Person.objects.create(
            name="Tim Andrews Here",
            normalized_name="tim andrews here",
        )
        Appearance.objects.create(episode=episode, person=tim, role=Appearance.Role.GUEST)
        Appearance.objects.create(episode=episode, person=tim_here, role=Appearance.Role.GUEST)
        call_command("sync_person_entities")
        call_command(
            "generate_person_entity_candidates",
            "--min-observations",
            "1",
            "--limit-pairs",
            "10",
        )

        call_command("score_person_entity_candidates")

        pair = PersonEntityCandidatePair.objects.get()
        assert pair.model_name == "person-entity-heuristic-v1"
        assert pair.match_probability is not None
        assert pair.features["heuristic_reasons"]

    def test_interactive_labeling_persists_human_labels(self) -> None:
        from podcast_network.web.catalog.management.commands.label_person_entity_candidates import (
            interactive_label_pairs,
            select_labeling_candidates,
        )

        podcast = Podcast.objects.create(name="Example Show")
        episode = Episode.objects.create(podcast=podcast, guid="episode-1", title="Episode 1")
        tim = Person.objects.create(name="Tim Andrews", normalized_name="tim andrews")
        tim_here = Person.objects.create(
            name="Tim Andrews Here",
            normalized_name="tim andrews here",
        )
        Appearance.objects.create(episode=episode, person=tim, role=Appearance.Role.GUEST)
        Appearance.objects.create(episode=episode, person=tim_here, role=Appearance.Role.GUEST)
        call_command("sync_person_entities")
        call_command(
            "generate_person_entity_candidates",
            "--min-observations",
            "1",
            "--limit-pairs",
            "10",
        )
        call_command("score_person_entity_candidates")

        pairs = select_labeling_candidates(
            limit=1,
            min_score=0,
            max_score=1,
            include_labeled=False,
            order="uncertain",
        )
        stats = interactive_label_pairs(
            pairs=pairs,
            source="test_human",
            dry_run=False,
            input_func=lambda _prompt: "y",
            output_func=lambda _message: None,
        )

        assert stats.matches == 1
        label = PersonEntityPairLabel.objects.get()
        assert label.label == PersonEntityPairLabel.Label.MATCH
        assert label.source == "test_human"
        assert label.pair_id_snapshot == pairs[0].pair_id
        assert label.features["token_jaccard"] > 0

    def test_select_labeling_candidates_skips_labeled_by_default(self) -> None:
        from podcast_network.web.catalog.management.commands.label_person_entity_candidates import (
            select_labeling_candidates,
        )

        podcast = Podcast.objects.create(name="Example Show")
        episode = Episode.objects.create(podcast=podcast, guid="episode-1", title="Episode 1")
        tim = Person.objects.create(name="Tim Andrews", normalized_name="tim andrews")
        tim_here = Person.objects.create(
            name="Tim Andrews Here",
            normalized_name="tim andrews here",
        )
        Appearance.objects.create(episode=episode, person=tim, role=Appearance.Role.GUEST)
        Appearance.objects.create(episode=episode, person=tim_here, role=Appearance.Role.GUEST)
        call_command("sync_person_entities")
        call_command(
            "generate_person_entity_candidates",
            "--min-observations",
            "1",
            "--limit-pairs",
            "10",
        )
        call_command("score_person_entity_candidates")
        pair = PersonEntityCandidatePair.objects.get()
        PersonEntityPairLabel.objects.create(
            pair=pair,
            label=PersonEntityPairLabel.Label.NOT_MATCH,
            features=pair.features,
        )

        assert select_labeling_candidates(
            limit=10,
            min_score=0,
            max_score=1,
            include_labeled=False,
            order="uncertain",
        ) == []
        assert select_labeling_candidates(
            limit=10,
            min_score=0,
            max_score=1,
            include_labeled=True,
            order="uncertain",
        ) == [pair]

    def test_labels_survive_candidate_pair_deletion(self) -> None:
        podcast = Podcast.objects.create(name="Example Show")
        episode = Episode.objects.create(podcast=podcast, guid="episode-1", title="Episode 1")
        tim = Person.objects.create(name="Tim Andrews", normalized_name="tim andrews")
        tim_here = Person.objects.create(
            name="Tim Andrews Here",
            normalized_name="tim andrews here",
        )
        Appearance.objects.create(episode=episode, person=tim, role=Appearance.Role.GUEST)
        Appearance.objects.create(episode=episode, person=tim_here, role=Appearance.Role.GUEST)
        call_command("sync_person_entities")
        call_command(
            "generate_person_entity_candidates",
            "--min-observations",
            "1",
            "--limit-pairs",
            "10",
        )
        pair = PersonEntityCandidatePair.objects.get()
        pair_id = pair.pair_id
        PersonEntityPairLabel.objects.create(
            pair=pair,
            pair_id_snapshot=pair_id,
            label=PersonEntityPairLabel.Label.MATCH,
            features=pair.features,
        )

        pair.delete()

        label = PersonEntityPairLabel.objects.get()
        assert label.pair is None
        assert label.pair_id_snapshot == pair_id
