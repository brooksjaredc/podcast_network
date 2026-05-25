from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from django.core.management.base import CommandError
from django.db import connection


def require_destructive_confirmation(
    *,
    action: str,
    confirmed: bool,
    database_vendor: str | None = None,
) -> None:
    vendor = database_vendor or connection.vendor
    if vendor != "postgresql":
        return
    if confirmed or env_allows_destructive_commands():
        return
    raise CommandError(
        f"{action} requires --confirm-destructive when running against Postgres. "
        "Use this only after verifying the target DATABASE_URL."
    )


def env_allows_destructive_commands() -> bool:
    return os.environ.get("PODCAST_NETWORK_ALLOW_DESTRUCTIVE", "").lower() in {
        "1",
        "true",
        "yes",
    }


@contextmanager
def database_statement_timeout(milliseconds: int) -> Iterator[None]:
    if milliseconds <= 0 or connection.vendor != "postgresql":
        yield
        return
    with connection.cursor() as cursor:
        cursor.execute("SHOW statement_timeout")
        previous = cursor.fetchone()[0]
        cursor.execute("SET statement_timeout = %s", [milliseconds])
    try:
        yield
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SET statement_timeout = %s", [previous])
