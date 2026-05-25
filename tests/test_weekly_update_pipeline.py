from __future__ import annotations

from podcast_network.web.catalog.management.commands.run_weekly_update_pipeline import (
    TODO_NOTES,
    build_pipeline_steps,
    should_warm_graph,
)


def test_weekly_update_plan_defaults_to_new_episode_extraction() -> None:
    options = default_options()

    steps = build_pipeline_steps(options)

    assert [step.command for step in steps] == [
        "ingest_feeds",
        "run_guest_extraction_batch_backfill",
        "sync_guest_appearances",
        "promote_frequent_guests_to_cohosts",
        "refresh_person_entity_resolution",
        "calculate_network_metrics",
        "calculate_network_evolution",
        "audit_future_link_weekly_new_links",
        "score_future_link_predictions",
        "generate_static_plots",
    ]
    batch_step = steps[1]
    assert batch_step.options["new_episodes_only"] is True
    assert batch_step.options["prompt_version"] == "guest-extraction-v7"
    assert batch_step.options["max_first_pass_batches"] == 0
    assert batch_step.options["first_pass_reasoning_effort"] == "low"
    assert batch_step.options["coordinator_label"].startswith("weekly-update-")
    sync_step = steps[2]
    assert sync_step.options["extraction_run_label"] == batch_step.options["coordinator_label"]
    scrape_step = steps[0]
    assert scrape_step.options["raw_snapshot_storage"] == "none"
    assert scrape_step.options["max_episodes_per_feed"] == 500
    assert scrape_step.options["run_label"] == batch_step.options["coordinator_label"]
    promotion_step = steps[3]
    assert promotion_step.options["threshold"] == 100
    assert promotion_step.options["episode_share_threshold"] == 0.20
    evolution_step = steps[6]
    assert evolution_step.options["max_weeks"] == 1
    assert evolution_step.options["betweenness_sample_size"] == 200
    assert evolution_step.options["closeness_sample_size"] == 200
    assert steps[5].options["run_label"] == batch_step.options["coordinator_label"]
    assert evolution_step.options["run_label"] == batch_step.options["coordinator_label"]
    er_step = steps[4]
    assert er_step.options["limit_pairs"] == 20000
    audit_step = steps[7]
    assert (
        audit_step.options["model_path"]
        == "data/models/future_link_exact_lr_unweighted_onecut.joblib"
    )
    assert audit_step.options["run_id"] == batch_step.options["coordinator_label"]
    prediction_step = steps[8]
    assert prediction_step.options["top_n"] == 1000
    plot_step = steps[9]
    assert plot_step.options["output_dir"] == "static/plots"


def test_weekly_update_plan_can_reprocess_current_prompt() -> None:
    options = default_options()
    options["reprocess_current_prompt"] = True

    steps = build_pipeline_steps(options)

    assert steps[1].options["new_episodes_only"] is False


def test_weekly_update_plan_can_run_independent_cloud_job_phases() -> None:
    expected_commands_by_phase = {
        "scrape": ["ingest_feeds"],
        "llm": ["run_guest_extraction_batch_backfill"],
        "processing-er": [
            "sync_guest_appearances",
            "promote_frequent_guests_to_cohosts",
            "refresh_person_entity_resolution",
        ],
        "metrics": ["calculate_network_metrics", "calculate_network_evolution"],
        "predictions": [
            "audit_future_link_weekly_new_links",
            "score_future_link_predictions",
            "generate_static_plots",
        ],
        "plots": ["generate_static_plots"],
    }

    for phase, expected_commands in expected_commands_by_phase.items():
        options = default_options()
        options["phase"] = phase

        steps = build_pipeline_steps(options)

        assert [step.command for step in steps] == expected_commands


def test_weekly_update_predictions_can_use_gcs_model_uri() -> None:
    options = default_options()
    options["phase"] = "predictions"
    options["future_link_gcs_model_uri"] = "gs://bucket/models/future_link.joblib"

    steps = build_pipeline_steps(options)

    assert steps[0].options["model_path"] == ""
    assert steps[0].options["gcs_model_uri"] == "gs://bucket/models/future_link.joblib"


def test_weekly_update_only_warms_graph_for_metric_phase() -> None:
    options = default_options()

    options["phase"] = "scrape"
    assert should_warm_graph(options) is False

    options["phase"] = "metrics"
    assert should_warm_graph(options) is True

    options["skip_graph_warm"] = True
    assert should_warm_graph(options) is False


def test_weekly_update_todos_document_future_processing_hooks() -> None:
    assert any("topic-only false positives" in note for note in TODO_NOTES)
    assert any("single-name resolution" in note for note in TODO_NOTES)
    assert not any("future-guest feature rebuild" in note for note in TODO_NOTES)
    assert not any("plots read from Postgres" in note for note in TODO_NOTES)


def default_options() -> dict[str, object]:
    return {
        "feed_timeout": 20,
        "feed_concurrency": 8,
        "feed_progress_every": 50,
        "max_feed_mb": 50.0,
        "max_episodes_per_feed": 500,
        "raw_snapshot_storage": "none",
        "include_inactive_feeds": False,
        "first_pass_batch_size": 1000,
        "max_first_pass_batches": 0,
        "first_pass_model": "gpt-5-nano",
        "first_pass_reasoning_effort": "low",
        "second_pass_model": "gpt-5-mini",
        "second_pass_reasoning_effort": "medium",
        "prompt_version": "guest-extraction-v7",
        "coordinator_label": "",
        "llm_output_dir": "/tmp/podcast-network-batches",
        "poll_interval_seconds": 300,
        "review_min_confidence": 0.75,
        "review_max_confidence": 0.90,
        "min_guest_confidence": 0.90,
        "cohost_threshold": 100,
        "cohost_episode_share_threshold": 0.20,
        "entity_limit_pairs": 20000,
        "entity_min_score": 0.5,
        "entity_min_observations": 1,
        "evolution_max_weeks": 1,
        "evolution_person_metric_limit": 100,
        "evolution_betweenness_sample_size": 200,
        "evolution_closeness_sample_size": 200,
        "future_link_model_path": "data/models/future_link_exact_lr_unweighted_onecut.joblib",
        "future_link_gcs_model_uri": "",
        "future_link_top_n": 1000,
        "future_link_batch_size": 200000,
        "future_link_max_degree": 3,
        "plot_output_dir": "static/plots",
        "plot_gcs_output_uri": "",
        "reprocess_current_prompt": False,
        "skip_scrape": False,
        "skip_llm": False,
        "skip_processing": False,
        "skip_entity_resolution": False,
        "skip_network_metrics": False,
        "skip_network_evolution": False,
        "skip_future_link_predictions": False,
        "skip_static_plots": False,
        "skip_graph_warm": False,
        "phase": "all",
    }
