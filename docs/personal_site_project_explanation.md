# Personal Site Project Explanation Draft

This document is a raw material bank for explaining the podcast network website on
a personal website, portfolio page, resume extension, project case study, or interview
conversation. The framing should stay grounded: this was a fun analytical experiment
with interesting features to play with, built with serious data, ML, graph, product,
and web engineering skills.

## Short Project Framing

I built an interactive podcast network analysis website that lets people explore how
podcasts, hosts, and guests are connected. The project started as a playful "six
degrees" idea, but grew into a full data product: it scrapes podcast metadata, uses
multi-step LLM extraction to identify guests, resolves messy person names into
canonical entities, builds graph representations of the podcast ecosystem, calculates
network metrics and historical trends, powers interactive search and recommendation
features, and trains ML models to predict plausible future guest appearances.

The result is both a fun site to browse and a substantial end-to-end technical system:
data ingestion, LLM workflows, entity resolution, relational modeling, graph analytics,
machine learning, automation, visualization, UX design, and production deployment.

## One-Paragraph Portfolio Version

Built a Django/Postgres web app for exploring podcast guest connections as a fun
analytical experiment. The system ingests podcast feeds, extracts guest names from
episode metadata using a multi-stage OpenAI Batch API workflow, resolves noisy names
into canonical people, constructs host/guest and podcast-similarity graphs, calculates
centrality and evolution metrics, and exposes the results through interactive features
like Six Degrees path search, network maps, rankings, recommendations, and experimental
future-guest predictions. I also built the automated weekly update pipeline that
scrapes new data, reruns extraction and entity resolution, refreshes graph metrics,
regenerates plots, scores ML predictions, audits newly published links, and reports
pipeline status.

## Skills Demonstrated

### Data Acquisition And Ingestion

- Built scraping and ingestion pipelines for a corpus of podcast and chart/feed
  sources, including Apple/Spotify chart feed imports, RSS ingestion, and legacy
  feed migration.
- Parsed podcast RSS data into structured records for podcasts, feeds, episodes,
  metadata, descriptions, publication dates, media URLs, and raw feed snapshots.
- Added feed health and operational safeguards, including timeout controls,
  concurrency limits, max feed size limits, HTTP status tracking, ETag/Last-Modified
  handling, failure counts, and raw snapshot storage.
- Designed ingestion to support both local development and production-shaped data
  processing, with SQLite for quick iteration and Postgres for the app database.
- Preserved raw and parsed data so downstream extraction, debugging, and reprocessing
  could be performed without repeatedly refetching the same sources.

### LLM Guest Extraction

- Designed an elaborate multi-step LLM prompting system for extracting episode guests
  from messy podcast titles and descriptions.
- Built prompts with detailed exclusion rules for false positives such as episode
  topics, public figures being discussed, authors in book titles, athletes in sports
  headlines, regular hosts, producers, organizations, sponsors, and non-person entities.
- Included known host context in prompts so the model can avoid incorrectly labeling
  regular hosts or co-hosts as guests.
- Used a versioned prompt workflow so extraction behavior can be tracked, compared,
  and safely reprocessed over time.
- Implemented OpenAI Batch API workflows for high-volume extraction, with first-pass
  extraction, second-pass review bands, confidence thresholds, batch artifact storage,
  polling, syncing, and backfill commands.
- Stored structured extraction outputs, candidate guests, confidence scores, evidence,
  model metadata, prompt versions, and extraction run status for auditability.
- Built tooling to estimate extraction cost, sample episodes for review, rerun review
  bands, sync batch outputs, and backfill missed extraction runs.

### Entity Resolution And Name Normalization

- Built a multi-step entity-resolution system to turn raw extracted guest names into
  canonical person entities.
- Normalized names while preserving display names, aliases, observations, roles,
  source context, confidence, and first/last seen timestamps.
- Created stable IDs for person observations, canonical entities, candidate pairs, and
  links so the database can be rebuilt and updated consistently.
- Generated candidate entity pairs using blocking keys and name/observation features.
- Trained and applied an entity matching model for likely duplicate person entities.
- Supported human/active-learning style labels for candidate pairs, including match,
  non-match, skip, model score, feature snapshot, and notes.
- Added single-name and alias handling for ambiguous extracted names.
- Built commands to refresh entity resolution, score candidate pairs, apply known
  aliases, apply accepted matches, and sync guest appearances into canonical entities.

### Database And Data Modeling

- Designed a mature relational schema around podcasts, feeds, raw feed snapshots,
  episodes, people, appearances, observations, canonical person entities, extraction
  runs, entity links, network metric runs, evolution snapshots, prediction runs, and
  pipeline execution records.
- Used Django models, migrations, constraints, indexes, JSON fields, and bulk creation
  patterns to keep the system structured and queryable.
- Added uniqueness constraints for important domain concepts, such as podcast/feed
  identity, episode GUIDs, raw snapshot hashes, episode/person/role appearances,
  entity candidate pairs, and prediction pairs per run.
- Modeled pipeline runs and step runs with statuses, timestamps, options, metadata,
  elapsed time, errors, and ordered execution, making the system observable and
  debuggable rather than just a collection of scripts.
- Supported local and cloud database workflows, including SQLite-to-Postgres copying,
  Postgres deployment, read-only cloud inspection, and production preflight checks.

### Graph And Network Analysis

- Built graph representations for host/guest relationships, person-to-person
  relationships, and podcast similarity relationships.
- Used NetworkX to calculate graph metrics such as PageRank, HITS hub/authority,
  closeness centrality, betweenness centrality, degree centrality, density,
  clustering, transitivity, connected components, and shortest paths.
- Designed weighted graph edges from repeated guest/host interactions and shared
  podcast guest overlap.
- Created rankings for people and podcasts based on centrality and activity metrics.
- Added approximate/sample-based metric calculations for expensive graph algorithms
  so large graphs remain practical to update.
- Built category and overlap analysis surfaces, including category mixing and bias
  views.

### Network Evolution Study

- Built a historical network evolution pipeline that reconstructs graph snapshots by
  week.
- Calculated time-based network structure metrics such as person nodes, person edges,
  podcast counts, episode counts, guest appearance counts, new people, new edges, new
  podcasts, largest component size, density, clustering, transitivity, and average
  shortest path length.
- Stored weekly snapshots and per-person evolution metrics so the website can show
  how the graph changes over time instead of only showing a current static graph.
- Supported bootstrap, recompute, incremental missing-week updates, and capped weekly
  processing for production automation.

### Interactive Features

- Built a Six Degrees path search feature that finds the shortest path between two
  people through podcast host/guest relationships.
- Added name resolution and fuzzy suggestions for path searches when a person is not
  found exactly.
- Added date-window filtering to path search so users can ask how connections existed
  during specific time periods.
- Built interactive graph/network map plots for people and podcasts, plus static SVG
  and HTML Plotly artifacts for rankings, distributions, categories, and evolution.
- Built podcast recommendation features based on shared guest overlap, overlap rate,
  genre filters, active-only filtering, exclusions, sorting, and explanation text.
- Built comparison/common-guest tooling so users can inspect overlap between selected
  podcasts.
- Built rankings, browse pages, person detail pages, podcast detail pages, methods
  pages, prediction pages, and analysis views that expose the underlying analysis in
  user-facing ways.

### Machine Learning Future-Guest Prediction

- Built an ML pipeline to predict likely future podcast-guest links.
- Carefully defined the prediction unit as a `(cutoff date, podcast, canonical person)`
  candidate, excluding people who had already appeared on the podcast before the cutoff.
- Designed labels based on whether a guest appeared on a podcast within a future
  prediction horizon after the cutoff.
- Used sliding/rolling date windows to turn historical time into training examples.
- Paid attention to temporal leakage, time-blocked evaluation, repeated entities, and
  the difference between balanced exploration datasets and real imbalanced ranking
  datasets.
- Curated training sets with degree-limited candidate generation, deterministic
  train/test assignment, positive/negative sampling, and full-imbalance feature
  matrices.
- Engineered features from graph structure, podcast activity, guest activity, recency,
  repeat behavior, category compatibility, shared neighbors, and centrality signals.
- Compared model families including logistic regression and XGBoost.
- Ran feature selection, hyperparameter grid search, class-weight experiments, ranking
  metrics, score histograms, calibration considerations, and production scoring.
- Stored prediction runs, feature names, model metadata, scored candidates, ranks,
  distances, scores, and weekly audit records for newly published guest links.

### Data Engineering And Performance

- Used chunked iterators, bulk inserts, batching, deterministic hashes, indexed fields,
  and compressed/artifact-based workflows to make large data processing manageable.
- Built memory-mapped feature matrices for large ML experiments rather than relying on
  enormous CSV files.
- Designed batch sizes and limits for feed scraping, extraction, entity resolution,
  future-link scoring, and graph metric calculations.
- Added commands for reproducible rebuilds of guest appearances, metrics, plots,
  predictions, entity resolution, and training data.
- Separated local experimentation from production runs so development remained fast
  while cloud workflows could handle larger jobs.

### Automation And Production Operations

- Built an automated weekly update pipeline covering scraping, LLM guest extraction,
  appearance materialization, co-host promotion, entity resolution, network metrics,
  network evolution, future-link audits, prediction scoring, static plot generation,
  and graph warmup.
- Orchestrated production jobs with Google Cloud Workflows and Cloud Run jobs,
  including preflight checks, scrape jobs, LLM jobs, processing/entity-resolution jobs,
  metrics jobs, prediction jobs, status checks, and success/failure alerts.
- Stored artifacts in Google Cloud Storage, including raw feed snapshots, OpenAI batch
  files, model artifacts, and generated static plots.
- Added operational status views and commands for weekly update status, production
  preflight, alerts, and failure visibility.
- Containerized the app for deployment parity with Docker/Gunicorn/WhiteNoise and
  production Django settings.

### Product Sense And UX

- Translated a technically complex graph/ML project into features that are easy and
  fun to play with: Six Degrees, Map, Recommendations, Rankings, Podcasts, People,
  Analysis, Methods, and Experimental Predictions.
- Reworked the information architecture around user jobs rather than implementation
  folders.
- Kept advanced methodology available without forcing it into the first-time user flow.
- Designed prediction surfaces to feel experimental and appropriately caveated, with
  "why" explanations where possible.
- Added starter searches, filters, sorting, empty-state recovery, active navigation,
  detail-page summaries, metric context, and clearer result actions.
- Balanced exploratory fun with credibility: users can play with the site casually,
  but the interface still reveals how the data was generated and where uncertainty
  enters the system.

### Visual Design

- Created a warmer, more polished visual identity around an analytical podcast
  experiment rather than a generic analytics dashboard.
- Designed page patterns for command surfaces, dossier-style person/podcast detail
  pages, dense but readable tables, plot sections, ranking pages, and recommendation
  result cards.
- Built an editorial-style homepage hero, branded favicon/header mark, consistent
  focus states, active navigation, footer, semantic badges, numeric alignment, and
  responsive layouts.
- Improved graph/path visual styling so the core features feel distinctive without
  sacrificing readability.
- Preserved the efficiency of data-heavy pages while making the primary interactive
  features feel more inviting.

### Testing And Quality

- Added tests across ingestion, guest extraction, host extraction, entity resolution,
  name frequency, network metrics, network evolution, Six Degrees paths, plot
  generation, future-link features, future-link prediction, future-link training,
  weekly update pipeline behavior, production preflight, artifact metadata, and web
  pages.
- Used tests to protect important workflows while iterating across data pipelines,
  graph analytics, ML, and Django views.
- Built the project as a maintained system rather than a one-off notebook: commands,
  docs, migrations, tests, deployment config, and repeatable pipelines all live in
  the same repo.

## Tools And Technologies

- Python
- Django
- Postgres and SQLite
- Django ORM and migrations
- NetworkX
- pandas, NumPy, SciPy
- scikit-learn
- XGBoost
- Plotly
- OpenAI API and OpenAI Batch API
- Pydantic
- feedparser
- Google Cloud Run
- Google Cloud Workflows
- Google Cloud Storage
- Docker
- Gunicorn
- WhiteNoise
- pytest
- Ruff

## Resume Bullet Bank

- Built an end-to-end Django/Postgres data product for exploring podcast host/guest
  connections, from feed scraping and LLM extraction through graph analytics,
  recommendations, ML predictions, and production automation.
- Designed a multi-stage OpenAI Batch API extraction workflow that identifies podcast
  guests from messy episode metadata while filtering out hosts, topics, organizations,
  sponsors, and other common false positives.
- Implemented canonical person entity resolution with stable IDs, candidate pair
  generation, model scoring, alias handling, human labels, and repeatable refresh
  commands.
- Modeled a production-ready relational database for podcasts, feeds, episodes,
  appearances, extraction runs, entity links, graph metrics, historical snapshots,
  ML prediction runs, and pipeline step observability.
- Built graph analysis pipelines using NetworkX to calculate PageRank, HITS,
  closeness, betweenness, degree centrality, podcast similarity, graph structure
  metrics, and shortest paths.
- Created a historical network evolution system that reconstructs weekly graph
  snapshots and tracks structural change over time.
- Developed interactive website features including Six Degrees path search, podcast
  recommendations, common guest comparison, ranking tables, detail pages, Plotly map
  visualizations, and experimental future-guest prediction views.
- Trained future-link prediction models with temporal cutoffs, sliding windows,
  curated candidate sets, feature engineering, deterministic splits, hyperparameter
  search, model comparison, ranking metrics, and calibrated production scoring.
- Automated weekly production updates across scraping, LLM extraction, entity
  resolution, graph rebuilding, metric/evolution calculations, plot generation, ML
  prediction scoring, new-link audits, and status alerts.
- Led the product and visual design of the site, turning a complex analytical backend
  into a playful, understandable interface with strong navigation, clear workflows,
  polished detail pages, readable tables, and thoughtful caveats.

## Case Study Structure

### 1. The Hook

Start with the playful question:

> What if you could find the shortest podcast-appearance path between two public
> figures, then browse the graph around them?

Then explain that the fun surface required a serious backend: scraping, LLM
extraction, entity resolution, graph analysis, ML prediction, automation, and web
design.

### 2. The Data Problem

Podcast metadata is messy. Guest names are embedded in titles, descriptions, show
notes, "guest:" lists, headlines, topical discussion blurbs, sponsor text, book
titles, and regular-host descriptions. The first major challenge was turning this
unstructured text into a reliable graph of who appeared where.

### 3. The Extraction System

Describe the multi-step LLM workflow: versioned prompts, known-host context,
structured outputs, confidence thresholds, evidence capture, batch processing,
review bands, and extraction run metadata.

### 4. The Identity Problem

Explain why name resolution matters: the same person can appear under variants,
aliases, initials, nicknames, casing differences, or extraction artifacts. The entity
resolution layer creates canonical people from raw observations.

### 5. The Graph Layer

Explain the graph model: podcasts connect to guests and hosts; people connect through
shared podcast appearances; podcasts connect through shared guests. From there, the
site can calculate shortest paths, centrality metrics, rankings, similarity, and
evolution over time.

### 6. The Product Layer

Explain how the analysis became usable features: Six Degrees, Map, Recommendations,
Rankings, People, Podcasts, Analysis, Methods, and Experimental Predictions. The key
product move was making the site fun to poke around in while still making the
methodology transparent.

### 7. The ML Layer

Explain future-link prediction as an experimental recommender-style modeling problem:
given the graph at a cutoff date, rank people who have not yet appeared on a podcast
by how likely they are to appear in the future.

### 8. The Automation Layer

Explain that the project is not a static analysis. A weekly pipeline updates the
underlying data, reruns extraction and resolution, refreshes graph metrics, regenerates
plots, scores predictions, audits new links, and reports status.

### 9. What It Demonstrates

Close by tying the project to broader skills:

- End-to-end product engineering
- Data engineering
- Applied LLM systems
- Entity resolution
- Graph analytics
- Machine learning
- Web development
- UX/product judgment
- Production automation
- Testing and operational maturity

## Possible Personal Website Sections

### Compact Project Card

**Podcast Network Explorer**  
An interactive Django/Postgres web app for exploring podcast guest connections. Built
feed ingestion, LLM guest extraction, entity resolution, graph metrics, shortest-path
search, recommendations, Plotly network maps, ML future-guest predictions, and an
automated weekly cloud update pipeline.

### Technical Deep Dive Intro

This project looks playful on the surface: type two names, find their podcast
connection path, browse related shows, and see who might plausibly appear where next.
Underneath, it is a full-stack data system that turns messy podcast metadata into a
queryable graph and keeps that graph fresh through automated production jobs.

### Skills List For Sidebar

- Full-stack web app development
- Django/Postgres data modeling
- RSS/feed scraping and parsing
- LLM prompt design and batch extraction
- Entity resolution and canonicalization
- Graph algorithms and network analysis
- Recommendation systems
- Machine learning classification/ranking
- Feature engineering and model evaluation
- Data pipeline automation
- Cloud deployment and operations
- Product strategy and UX design
- Visual/interface design
- Testing and maintainability

## Phrases To Reuse

- "a fun analytical experiment with a serious data backend"
- "turning messy podcast metadata into an explorable graph"
- "interactive shortest-path search through podcast appearances"
- "LLM-assisted extraction with structured outputs, confidence thresholds, and audit
  trails"
- "canonical entity resolution for noisy guest names"
- "network-based recommendations driven by shared guest overlap"
- "future-link prediction for plausible upcoming guest appearances"
- "weekly automated rebuilds of the graph, metrics, plots, and predictions"
- "playful surface area, production-minded data engineering underneath"

## Phrases To Avoid

- Grand culture-map framing that makes the project sound more self-serious than fun
- "generic analytics dashboard"
- "AI-powered" without specifics
- Overstating the prediction model as definitive rather than experimental
