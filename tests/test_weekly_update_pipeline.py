from __future__ import annotations

from podcast_network.web.catalog.management.commands.run_weekly_update_pipeline import (
    TODO_NOTES,
    build_pipeline_steps,
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
    ]
    batch_step = steps[1]
    assert batch_step.options["new_episodes_only"] is True
    assert batch_step.options["prompt_version"] == "guest-extraction-v7"
    assert batch_step.options["max_first_pass_batches"] == 0
    assert batch_step.options["first_pass_reasoning_effort"] == "low"
    assert batch_step.options["coordinator_label"].startswith("weekly-update-")
    scrape_step = steps[0]
    assert scrape_step.options["raw_snapshot_storage"] == "none"
    assert scrape_step.options["max_episodes_per_feed"] == 500
    promotion_step = steps[3]
    assert promotion_step.options["threshold"] == 100
    assert promotion_step.options["episode_share_threshold"] == 0.20
    evolution_step = steps[-1]
    assert evolution_step.options["max_weeks"] == 1


def test_weekly_update_plan_can_reprocess_current_prompt() -> None:
    options = default_options()
    options["reprocess_current_prompt"] = True

    steps = build_pipeline_steps(options)

    assert steps[1].options["new_episodes_only"] is False


def test_weekly_update_todos_document_future_processing_hooks() -> None:
    assert any("topic-only false positives" in note for note in TODO_NOTES)
    assert any("single-name resolution" in note for note in TODO_NOTES)
    assert any("future-guest feature rebuild" in note for note in TODO_NOTES)
    assert any("plots read from Postgres" in note for note in TODO_NOTES)


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
        "reprocess_current_prompt": False,
        "skip_scrape": False,
        "skip_llm": False,
        "skip_processing": False,
        "skip_entity_resolution": False,
        "skip_network_metrics": False,
        "skip_network_evolution": False,
    }
