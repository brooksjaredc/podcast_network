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
