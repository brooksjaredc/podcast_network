#!/usr/bin/env bash
set -euo pipefail

PROJECT="${GCP_PROJECT:-podcast-network-prod}"
REGION="${GCP_REGION:-us-central1}"
INSTANCE="${CLOUD_SQL_INSTANCE:-podcast-network-db}"
PORT="${CLOUD_SQL_PROXY_PORT:-5433}"
LOCAL_DATABASE_URL="${LOCAL_DATABASE_URL:-${DATABASE_URL:-postgresql:///podcast_network}}"

if [[ "${CONFIRM_SYNC_CLOUD_DB:-}" != "1" ]]; then
  cat >&2 <<EOF
Refusing to replace the local database without confirmation.

This streams the cloud database into your local database:
  local: ${LOCAL_DATABASE_URL}
  cloud: ${PROJECT}:${REGION}:${INSTANCE}

Run with:
  CONFIRM_SYNC_CLOUD_DB=1 make sync-cloud-db
EOF
  exit 2
fi

if ! command -v cloud-sql-proxy >/dev/null 2>&1; then
  echo "cloud-sql-proxy is required. Install it with: brew install cloud-sql-proxy" >&2
  exit 127
fi

if ! command -v pg_dump >/dev/null 2>&1 || ! command -v pg_restore >/dev/null 2>&1; then
  echo "pg_dump and pg_restore are required. Install PostgreSQL client tools first." >&2
  exit 127
fi

proxy_pid=""
if ! lsof -iTCP:"${PORT}" -sTCP:LISTEN -n -P >/dev/null 2>&1; then
  cloud-sql-proxy \
    --gcloud-auth \
    "${PROJECT}:${REGION}:${INSTANCE}" \
    --port "${PORT}" >/tmp/podcast-network-cloud-sql-proxy.log 2>&1 &
  proxy_pid="$!"
  cleanup() {
    if [[ -n "${proxy_pid}" ]]; then
      kill "${proxy_pid}" >/dev/null 2>&1 || true
    fi
  }
  trap cleanup EXIT
  sleep 3
fi

CLOUD_DATABASE_URL="$(
  GCP_PROJECT="${PROJECT}" CLOUD_SQL_PROXY_PORT="${PORT}" python3 - <<'PY'
import os
import subprocess
from urllib.parse import quote, urlparse

raw = subprocess.check_output(
    [
        "gcloud",
        "secrets",
        "versions",
        "access",
        "latest",
        "--secret",
        "database-url",
        "--project",
        os.environ["GCP_PROJECT"],
    ],
    text=True,
).strip()
url = urlparse(raw)
if not url.username or not url.password:
    raise SystemExit("database-url secret must include username and password")
database = url.path.lstrip("/")
print(
    "postgresql://"
    f"{quote(url.username)}:{quote(url.password)}"
    f"@127.0.0.1:{os.environ['CLOUD_SQL_PROXY_PORT']}/{database}"
)
PY
)"

echo "Syncing cloud database to local database..."
pg_dump "${CLOUD_DATABASE_URL}" --format=custom --no-owner --no-acl \
  | pg_restore \
      --clean \
      --if-exists \
      --no-owner \
      --no-acl \
      --dbname "${LOCAL_DATABASE_URL}"
echo "Cloud database sync complete."
