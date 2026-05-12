from __future__ import annotations

from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from podcast_network.entity_model import (
    load_entity_model,
    predict_match_probability,
    save_entity_model,
    train_entity_model,
    train_logistic_entity_model,
)
from podcast_network.web.catalog.models import (
    Appearance,
    Episode,
    Person,
    PersonEntityCandidatePair,
    PersonEntityPairLabel,
    Podcast,
)


class PersonEntityModelTests(TestCase):
    def test_train_save_and_load_entity_model(self) -> None:
        examples = synthetic_examples()

        model = train_logistic_entity_model(
            examples=examples,
            model_name="test-person-entity-logistic",
        )
        path = Path(self.tmpdir) / "model.joblib"
        save_entity_model(model, path)
        loaded = load_entity_model(path)

        positive_probability = predict_match_probability(loaded, examples[0][0])
        negative_probability = predict_match_probability(loaded, examples[-1][0])

        assert loaded.model_name == "test-person-entity-logistic"
        assert loaded.training_examples == len(examples)
        assert positive_probability > negative_probability

    def test_train_save_and_load_xgboost_entity_model(self) -> None:
        examples = synthetic_examples()

        model = train_entity_model(
            examples=examples,
            model_name="test-person-entity-xgboost",
            model_type="xgboost",
        )
        path = Path(self.tmpdir) / "model.joblib"
        save_entity_model(model, path)
        loaded = load_entity_model(path)

        positive_probability = predict_match_probability(loaded, examples[0][0])
        negative_probability = predict_match_probability(loaded, examples[-1][0])

        assert loaded.model_name == "test-person-entity-xgboost"
        assert loaded.model_type == "xgboost"
        assert loaded.training_examples == len(examples)
        assert positive_probability > negative_probability

    def test_train_command_writes_model_artifact(self) -> None:
        pair = create_scored_candidate_pair()
        for index, (features, label) in enumerate(synthetic_examples()):
            PersonEntityPairLabel.objects.create(
                pair=pair,
                pair_id_snapshot=pair.pair_id,
                label=(
                    PersonEntityPairLabel.Label.MATCH
                    if label
                    else PersonEntityPairLabel.Label.NOT_MATCH
                ),
                source="test",
                match_probability=0.5,
                features={**features, "label_index": index},
            )
        output = Path(self.tmpdir) / "trained.joblib"
        metrics_output = Path(self.tmpdir) / "metrics.json"

        call_command(
            "train_person_entity_model",
            "--model-name",
            "test-trained-model",
            "--output",
            str(output),
            "--metrics-output",
            str(metrics_output),
        )

        loaded = load_entity_model(output)
        assert loaded.model_name == "test-trained-model"
        assert loaded.model_type == "xgboost"
        assert loaded.training_examples == len(synthetic_examples())
        assert metrics_output.exists()

    def test_score_command_can_use_trained_model(self) -> None:
        pair = create_scored_candidate_pair()
        model = train_logistic_entity_model(
            examples=synthetic_examples(),
            model_name="test-trained-model",
        )
        model_path = Path(self.tmpdir) / "trained.joblib"
        save_entity_model(model, model_path)

        call_command("score_person_entity_candidates", "--trained-model", str(model_path))

        pair.refresh_from_db()
        assert pair.model_name == "test-trained-model"
        assert pair.match_probability is not None

    def test_score_command_report_uses_trained_model_name(self) -> None:
        create_scored_candidate_pair()
        model = train_logistic_entity_model(
            examples=synthetic_examples(),
            model_name="test-trained-model",
        )
        model_path = Path(self.tmpdir) / "trained.joblib"
        report_path = Path(self.tmpdir) / "report.md"
        save_entity_model(model, model_path)

        call_command(
            "score_person_entity_candidates",
            "--trained-model",
            str(model_path),
            "--report",
            str(report_path),
        )

        assert "Model: `test-trained-model`" in report_path.read_text(encoding="utf-8")

    def setUp(self) -> None:
        self.tmpdir = self.enterContext(PathContext())


def synthetic_examples() -> list[tuple[dict, int]]:
    positives = [
        (
            {
                "name_sequence_ratio": 0.88,
                "token_jaccard": 0.67,
                "cleaned_name_sequence_ratio": 1.0,
                "cleaned_token_jaccard": 1.0,
                "same_cleaned_token_set": True,
                "same_cleaned_first_token": True,
                "same_cleaned_last_token": True,
                "shared_podcast_count": 1,
                "genre_jaccard": 0.5,
                "role_jaccard": 1.0,
                "has_graph_distance_proxy": True,
            },
            1,
        )
        for _ in range(8)
    ]
    negatives = [
        (
            {
                "name_sequence_ratio": 0.45,
                "token_jaccard": 0.33,
                "cleaned_name_sequence_ratio": 0.45,
                "cleaned_token_jaccard": 0.33,
                "same_cleaned_token_set": False,
                "same_cleaned_first_token": True,
                "same_cleaned_last_token": False,
                "shared_podcast_count": 1,
                "genre_jaccard": 1.0,
                "role_jaccard": 1.0,
                "has_graph_distance_proxy": True,
            },
            0,
        )
        for _ in range(8)
    ]
    return positives + negatives


def create_scored_candidate_pair() -> PersonEntityCandidatePair:
    podcast = Podcast.objects.create(name="Example Show")
    episode = Episode.objects.create(podcast=podcast, guid="episode-1", title="Episode 1")
    left = Person.objects.create(name="Dr. Zach Bush", normalized_name="dr zach bush")
    right = Person.objects.create(name="Zach Bush", normalized_name="zach bush")
    Appearance.objects.create(episode=episode, person=left, role=Appearance.Role.GUEST)
    Appearance.objects.create(episode=episode, person=right, role=Appearance.Role.GUEST)
    call_command("sync_person_entities")
    call_command(
        "generate_person_entity_candidates",
        "--min-observations",
        "1",
        "--limit-pairs",
        "10",
    )
    call_command("score_person_entity_candidates")
    return PersonEntityCandidatePair.objects.get()


class PathContext:
    def __enter__(self) -> Path:
        import tempfile

        self._tempdir = tempfile.TemporaryDirectory()
        return Path(self._tempdir.name)

    def __exit__(self, *exc_info: object) -> None:
        self._tempdir.cleanup()
