from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from psycopg import sql

CATALOG_TABLES = [
    "catalog_podcast",
    "catalog_scraperun",
    "catalog_extractionrun",
    "catalog_feed",
    "catalog_episode",
    "catalog_person",
    "catalog_rawfeedsnapshot",
    "catalog_scrapeerror",
    "catalog_episodeguestextraction",
    "catalog_guestcandidate",
    "catalog_podcasthostextraction",
    "catalog_hostcandidate",
    "catalog_appearance",
    "catalog_personobservation",
    "catalog_canonicalpersonentity",
    "catalog_personentitylink",
    "catalog_personentitycandidatepair",
    "catalog_personentitypairlabel",
]

BOOLEAN_COLUMNS = {
    "catalog_feed": {"active"},
    "catalog_episode": {"explicit"},
    "catalog_guestcandidate": {"accepted"},
}


class Command(BaseCommand):
    help = "Copy catalog data from the legacy SQLite database into the configured Postgres DB."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--sqlite-path",
            type=Path,
            default=settings.BASE_DIR / "db.sqlite3",
            help="Path to the source SQLite database.",
        )
        parser.add_argument(
            "--no-truncate",
            action="store_true",
            help="Append to existing Postgres rows instead of truncating catalog tables first.",
        )

    def handle(self, *args, **options) -> None:
        if connection.vendor != "postgresql":
            raise CommandError("The default Django database must be Postgres for this command.")

        sqlite_path: Path = options["sqlite_path"]
        if not sqlite_path.exists():
            raise CommandError(f"SQLite database does not exist: {sqlite_path}")

        source = sqlite3.connect(sqlite_path)
        source.row_factory = sqlite3.Row
        try:
            self.copy_tables(source, truncate=not options["no_truncate"])
        finally:
            source.close()

    def copy_tables(self, source: sqlite3.Connection, *, truncate: bool) -> None:
        with connection.cursor() as cursor:
            if truncate:
                tables = sql.SQL(", ").join(
                    sql.Identifier(table) for table in reversed(CATALOG_TABLES)
                )
                cursor.execute(
                    sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(tables),
                )

            for table in CATALOG_TABLES:
                columns = table_columns(source, table)
                copied = copy_table(source, cursor, table, columns)
                reset_sequence(cursor, table)
                self.stdout.write(f"Copied {copied:,} rows into {table}")


def table_columns(source: sqlite3.Connection, table: str) -> list[str]:
    rows = source.execute(f'PRAGMA table_info("{table}")').fetchall()
    if not rows:
        raise CommandError(f"Source table does not exist in SQLite database: {table}")
    return [row["name"] for row in rows]


def copy_table(source: sqlite3.Connection, cursor, table: str, columns: list[str]) -> int:
    column_sql = sql.SQL(", ").join(sql.Identifier(column) for column in columns)
    copy_sql = sql.SQL("COPY {} ({}) FROM STDIN").format(sql.Identifier(table), column_sql)
    select_sql = select_all_sql(table, columns)
    bool_columns = BOOLEAN_COLUMNS.get(table, set())
    copied = 0
    with cursor.copy(copy_sql) as copy:
        for row in source.execute(select_sql):
            copy.write_row(
                tuple(normalize_value(column, row[column], bool_columns) for column in columns)
            )
            copied += 1
    return copied


def select_all_sql(table: str, columns: list[str]) -> str:
    quoted_columns = ", ".join(f'"{column}"' for column in columns)
    return f'SELECT {quoted_columns} FROM "{table}" ORDER BY "{columns[0]}"'


def normalize_value(column: str, value: Any, bool_columns: set[str]) -> Any:
    if isinstance(value, str):
        value = value.replace("\x00", "")
    if column not in bool_columns or value is None:
        return value
    return bool(value)


def reset_sequence(cursor, table: str) -> None:
    cursor.execute(
        sql.SQL(
            """
            SELECT setval(
                pg_get_serial_sequence(%s, 'id'),
                COALESCE((SELECT MAX(id) FROM {}), 1),
                (SELECT COUNT(*) > 0 FROM {})
            )
            """
        ).format(sql.Identifier(table), sql.Identifier(table)),
        [table],
    )
