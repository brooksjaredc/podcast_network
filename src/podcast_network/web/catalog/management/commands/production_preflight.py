from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from podcast_network.cloud_artifacts import parse_gcs_uri


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    ok: bool
    detail: str


class Command(BaseCommand):
    help = "Validate production runtime configuration before running scheduled jobs."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--require-postgres", action="store_true")
        parser.add_argument("--require-production-settings", action="store_true")
        parser.add_argument("--require-gcs-artifacts", action="store_true")
        parser.add_argument("--future-link-model-path", default="")
        parser.add_argument("--future-link-gcs-model-uri", default="")
        parser.add_argument(
            "--skip-migration-check",
            action="store_true",
            help="Skip checking for unapplied Django migrations.",
        )

    def handle(self, *args: object, **options: object) -> None:
        checks = build_preflight_checks(
            require_postgres=bool(options["require_postgres"]),
            require_production_settings=bool(options["require_production_settings"]),
            require_gcs_artifacts=bool(options["require_gcs_artifacts"]),
            future_link_model_path=str(options["future_link_model_path"]),
            future_link_gcs_model_uri=str(options["future_link_gcs_model_uri"]),
            check_migrations=not bool(options["skip_migration_check"]),
        )
        failed = [check for check in checks if not check.ok]
        for check in checks:
            style = self.style.SUCCESS if check.ok else self.style.ERROR
            self.stdout.write(style(f"{check.name}: {check.detail}"))
        if failed:
            names = ", ".join(check.name for check in failed)
            raise CommandError(f"Production preflight failed: {names}")
        self.stdout.write(self.style.SUCCESS("Production preflight passed."))


def build_preflight_checks(
    *,
    require_postgres: bool,
    require_production_settings: bool,
    require_gcs_artifacts: bool,
    future_link_model_path: str,
    future_link_gcs_model_uri: str,
    check_migrations: bool,
) -> list[PreflightCheck]:
    checks = [
        database_vendor_check(require_postgres=require_postgres),
        migration_check(enabled=check_migrations),
        future_link_model_check(
            model_path=future_link_model_path,
            gcs_model_uri=future_link_gcs_model_uri,
        ),
    ]
    if require_production_settings:
        checks.extend(production_settings_checks())
    if require_gcs_artifacts:
        checks.extend(gcs_artifact_checks())
    return checks


def database_vendor_check(*, require_postgres: bool) -> PreflightCheck:
    vendor = connection.vendor
    ok = vendor == "postgresql" if require_postgres else vendor in {"postgresql", "sqlite"}
    requirement = "postgresql" if require_postgres else "postgresql or sqlite"
    return PreflightCheck(
        name="database_vendor",
        ok=ok,
        detail=f"{vendor} ({'expected ' + requirement})",
    )


def migration_check(*, enabled: bool) -> PreflightCheck:
    if not enabled:
        return PreflightCheck("migrations", True, "skipped")
    executor = MigrationExecutor(connection)
    targets = executor.loader.graph.leaf_nodes()
    plan = executor.migration_plan(targets)
    return PreflightCheck(
        name="migrations",
        ok=not plan,
        detail="all migrations applied" if not plan else f"{len(plan)} unapplied migration(s)",
    )


def production_settings_checks() -> list[PreflightCheck]:
    return [
        PreflightCheck(
            "django_debug",
            not settings.DEBUG,
            f"DEBUG={settings.DEBUG}",
        ),
        PreflightCheck(
            "django_secret_key",
            settings.SECRET_KEY != "dev-only-change-me",
            "custom secret configured"
            if settings.SECRET_KEY != "dev-only-change-me"
            else "default development secret",
        ),
        PreflightCheck(
            "allowed_hosts",
            any(host and host not in {"127.0.0.1", "localhost"} for host in settings.ALLOWED_HOSTS),
            ",".join(settings.ALLOWED_HOSTS),
        ),
        PreflightCheck(
            "secure_cookies",
            bool(settings.SESSION_COOKIE_SECURE and settings.CSRF_COOKIE_SECURE),
            (
                f"SESSION_COOKIE_SECURE={settings.SESSION_COOKIE_SECURE}, "
                f"CSRF_COOKIE_SECURE={settings.CSRF_COOKIE_SECURE}"
            ),
        ),
    ]


def gcs_artifact_checks() -> list[PreflightCheck]:
    return [
        gcs_uri_check("raw_snapshot_gcs_uri", settings.RAW_SNAPSHOT_GCS_URI),
        gcs_uri_check("batch_artifact_gcs_uri", settings.BATCH_ARTIFACT_GCS_URI),
        gcs_uri_check("plot_artifact_gcs_uri", settings.PLOT_ARTIFACT_GCS_URI),
        gcs_uri_check(
            "six_degrees_graph_artifact_gcs_uri",
            settings.SIX_DEGREES_GRAPH_ARTIFACT_GCS_URI,
        ),
    ]


def gcs_uri_check(name: str, uri: str) -> PreflightCheck:
    try:
        parse_gcs_uri(uri)
    except Exception as exc:
        return PreflightCheck(name, False, str(exc) if uri else "missing")
    return PreflightCheck(name, True, uri)


def future_link_model_check(*, model_path: str, gcs_model_uri: str) -> PreflightCheck:
    if gcs_model_uri:
        return gcs_uri_check("future_link_model", gcs_model_uri)
    if model_path:
        path = Path(model_path)
        return PreflightCheck(
            "future_link_model",
            path.exists(),
            str(path) if path.exists() else f"not found: {path}",
        )
    return PreflightCheck("future_link_model", True, "not configured")
