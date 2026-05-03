# Podcast Network

Modernized combined repo for the old podcast network analysis pipeline and web app.

The original project was split across:

- `../podcast_network_analysis`: data ingestion, cleaning, graph analysis, fixture generation
- `../podcast_connections`: Django web app backed by generated fixtures

This repo starts fresh and treats those projects as legacy references. The first milestone is a small vertical slice: load the old six-degrees graph data, answer path queries through a tested service, and expose it through a modern Django app shell.

## Local Setup

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

If Python 3.13 is not installed yet, Python 3.12 should also work for early development.

## Current Slice

```bash
python -m podcast_network.cli path "Joe Rogan" "Marc Maron"
python -m unittest
```

The CLI expects legacy graph files under `data/legacy/analysis/`.

