# Podcast Network

Modernized combined repo for the old podcast network analysis pipeline and web app.

The original project was split across:

- `../podcast_network_analysis`: data ingestion, cleaning, graph analysis, fixture generation
- `../podcast_connections`: Django web app backed by generated fixtures

This repo starts fresh and treats those projects as legacy references. The current app stores scraped podcast data, LLM guest extraction results, normalized people, and guest appearances in Django models that can run on SQLite for quick local work or Postgres for the real app database.

## Local Setup

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

If Python 3.13 is not installed yet, Python 3.12 should also work for early development.

## Database

By default, Django uses `db.sqlite3` in the repo root. To run against local Postgres:

```bash
brew install postgresql@17
brew services start postgresql@17
/opt/homebrew/opt/postgresql@17/bin/createdb podcast_network

export DATABASE_URL=postgresql:///podcast_network
python manage.py migrate
```

To copy the existing local SQLite catalog into Postgres:

```bash
DATABASE_URL=postgresql:///podcast_network \
  python manage.py copy_sqlite_to_postgres --sqlite-path db.sqlite3
```

To rebuild normalized guest appearances from stored LLM extraction candidates:

```bash
python manage.py sync_guest_appearances --clear --min-confidence 0.90
```

Set `DATABASE_URL` when running web commands if you want the app to read from Postgres:

```bash
DATABASE_URL=postgresql:///podcast_network python manage.py runserver
```

## Current Slice

```bash
python -m podcast_network.cli path "Joe Rogan" "Marc Maron"
python -m pytest
```

The Django web pages read from the catalog tables. The advanced plot pages still use the copied legacy analysis artifacts under `data/legacy/analysis/`.

## Development Workflow

For normal iteration, use a local Postgres database and keep cloud credentials out of
your everyday shell:

```bash
# If you do not already have a .env, start from the local template.
cp .env.local.example .env
make migrate
make dev
```

Use the cloud database only when you need to inspect production-shaped data. Start the
Cloud SQL Auth Proxy in one terminal:

```bash
make cloud-sql-proxy
```

Then run commands from another terminal with a cloud-read profile:

```bash
cp .env.cloud-read.example .env.cloud-read
set -a; source .env.cloud-read; set +a
python manage.py runserver
```

Environment variables loaded in the shell override `.env`, so this lets you inspect cloud
data without rewriting your local profile. Prefer a dedicated read-only Cloud SQL user
for that profile. The local database should remain the default for migrations, scraping
tests, and UI iteration; Docker is mainly for deployment parity and Cloud Run. Before
deploying, run:

```bash
make check
make deploy
```
