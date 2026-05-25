from __future__ import annotations

import pytest
from django.core.management.base import CommandError

from podcast_network.operational_safety import (
    database_statement_timeout,
    require_destructive_confirmation,
)


def test_destructive_confirmation_not_required_for_sqlite() -> None:
    require_destructive_confirmation(
        action="test action",
        confirmed=False,
        database_vendor="sqlite",
    )


def test_destructive_confirmation_required_for_postgres() -> None:
    with pytest.raises(CommandError, match="requires --confirm-destructive"):
        require_destructive_confirmation(
            action="test action",
            confirmed=False,
            database_vendor="postgresql",
        )


def test_destructive_confirmation_allows_confirmed_postgres() -> None:
    require_destructive_confirmation(
        action="test action",
        confirmed=True,
        database_vendor="postgresql",
    )


def test_database_statement_timeout_noops_for_zero() -> None:
    with database_statement_timeout(0):
        pass
