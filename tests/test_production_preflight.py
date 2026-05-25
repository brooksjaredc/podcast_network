from __future__ import annotations

from podcast_network.web.catalog.management.commands.production_preflight import (
    future_link_model_check,
    gcs_uri_check,
)


def test_gcs_uri_check_accepts_valid_uri() -> None:
    check = gcs_uri_check("artifact", "gs://bucket/path")

    assert check.ok is True
    assert check.detail == "gs://bucket/path"


def test_gcs_uri_check_rejects_missing_uri() -> None:
    check = gcs_uri_check("artifact", "")

    assert check.ok is False
    assert check.detail == "missing"


def test_future_link_model_check_accepts_gcs_uri() -> None:
    check = future_link_model_check(
        model_path="",
        gcs_model_uri="gs://bucket/model.joblib",
    )

    assert check.ok is True
