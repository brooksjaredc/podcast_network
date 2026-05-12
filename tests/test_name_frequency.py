from podcast_network.name_frequency import (
    shared_name_frequency_features,
    token_name_frequency_features,
)


def test_name_frequency_features_mark_common_names() -> None:
    features = token_name_frequency_features(("michael", "smith"))

    assert features["first_name_per_million"] > 0
    assert features["last_name_per_million"] > 0
    assert features["name_commonness_score"] > 0


def test_shared_name_frequency_features_only_count_shared_parts() -> None:
    common = shared_name_frequency_features(("michael", "smith"), ("michael", "j", "smith"))
    different_last = shared_name_frequency_features(("michael", "smith"), ("michael", "jones"))

    assert common["same_common_first_and_last_name"] is True
    assert common["shared_name_commonness_score"] > 0
    assert different_last["shared_first_name_per_million"] > 0
    assert different_last["shared_last_name_per_million"] == 0
    assert different_last["same_common_first_and_last_name"] is False
