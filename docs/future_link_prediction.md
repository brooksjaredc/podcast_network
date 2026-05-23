# Future Link Prediction Design Notes

## Goal

Predict likely future podcast-guest links: given the network as it existed at a cutoff date,
rank guest candidates for each podcast that have not previously appeared on that podcast.

The first version should produce an offline training/evaluation dataset and model artifacts from
cloud jobs. Later versions can power explorer recommendations and weekly "likely future guest"
rankings.

## Legacy Starting Point

The original implementation lives in:

- `../podcast_network_analysis/analyzing_functions/link_prediction.py`
- `../podcast_network_analysis/analyzing_functions/link_prediction_linux_final.py`

The legacy script:

- Builds a training graph from guest-podcast edges before a cutoff.
- Builds a test graph from guest-podcast edges before a later date.
- Creates one candidate row for every active podcast and every known guest who has not already
  appeared on that podcast.
- Labels `future_link = 1` when the podcast-guest edge exists in the later graph.
- Adds podcast metadata features, guest centrality features, podcast centrality features, category
  overlap, graph link-prediction scores, and duration-weighted overlap features.

Useful legacy feature columns include:

- Podcast activity: `num_guests`, `percent_unique`, `avg_day_diff`, `cat_bias`.
- Podcast centrality: `p_close`, `p_bt`, `p_degree`.
- Guest centrality: `g_pr`, `g_hubs`, `g_auths`, `g_close`, `g_bt`, `g_degree`.
- Compatibility: `same_cat`, resource allocation, Jaccard, Adamic-Adar, preferential attachment,
  community-aware common-neighbor scores.
- Weighted overlap: `guest_dur`, `host_dur`.

Main legacy limitations:

- Candidate generation is `active_podcasts * known_guests`, which will become infeasible as the
  catalog grows.
- It uses one or very few date cuts, leaving limited training data and making evaluation sensitive
  to the chosen period.
- It computes features in Python loops over many networkx calls, which is likely too slow for
  cloud-scale data.
- The training split is not explicit enough to avoid temporal leakage and repeated-entity bias.

## Current Data Sources

The current app has stronger normalized entities than the legacy repo:

- Podcasts: `Podcast`
- Episodes and dates: `Episode.published_at`
- Raw appearances: `Appearance`
- Normalized observations: `PersonObservation`
- Canonical people: `CanonicalPersonEntity`
- Observation-to-person links: `PersonEntityLink`
- Current metrics: `PersonNetworkMetric`, `PodcastNetworkMetric`
- Historical weekly person metrics: `NetworkEvolutionSnapshot`, `PersonNetworkEvolutionMetric`

The link-prediction pipeline should use `PersonEntityLink` joined through observations, episodes,
and podcasts as the source of truth. It should predict canonical person entities, not raw `Person`
rows.

## Prediction Unit

One row should represent:

```text
(cutoff_at, podcast_id, canonical_person_id)
```

Rules:

- The person must have appeared as a guest somewhere before `cutoff_at`.
- The podcast must exist before `cutoff_at`, preferably with enough interview history to support
  features.
- Exclude pairs where the person was already a guest on that podcast before `cutoff_at`.
- Usually exclude known hosts or cohosts of the target podcast.
- Label positive when the person appears as a guest on that podcast in:

```text
[cutoff_at, cutoff_at + prediction_horizon)
```

Initial horizon: 90 days.

## Date Cuts And Sliding Windows

Use many rolling date cuts to turn the time dimension into training data.

Candidate default:

- Cut frequency: weekly or monthly.
- Horizon: 90 days.
- Minimum history before first cutoff: 6-12 months.
- Optional gap between features and labels: 0-7 days if we want to avoid ambiguous publication
  timestamps or feed backfills.

Example:

```text
cutoff_at = 2025-01-01
features: all links before 2025-01-01
labels: links from 2025-01-01 through 2025-04-01
```

Then slide to the next cutoff.

Important: overlapping 90-day windows create correlated labels. That is fine for model training,
but evaluation should report by cutoff and use time-blocked holdouts so we do not mistake repeated
near-duplicate windows for independent performance.

### Training/Evaluation Structure

Use the full degree-limited candidate set for model training, but avoid storing all cuts in one
large database table. The first scaffold for this lives in:

- `src/podcast_network/future_link_training.py`
- `src/podcast_network/web/catalog/management/commands/plan_future_link_training.py`

The intended cloud workflow is:

1. Generate a rolling cutoff plan.
2. For each cutoff, build candidates and features from data before the cutoff.
3. Assign each row to train/test with a deterministic hash:

```text
hash(seed, cutoff_at, podcast_id, canonical_person_id) % 100
```

4. Write the cutoff's feature rows to a temporary compressed Parquet shard in object storage.
5. Run prequential evaluation: score the cutoff's test split with the current model, log metrics,
   then train or continue training on that cutoff's train split.
6. After evaluation, train a final production model on all historical train shards.
7. Retain model artifacts, metric rows, configs, and maybe test predictions; expire bulky feature
   shards after the run.

Preview command:

```bash
.venv/bin/python manage.py plan_future_link_training \
  --start-cutoff 2024-01-01 \
  --cut-frequency-days 30 \
  --horizon-days 90 \
  --min-history-days 365
```

The explicit `--start-cutoff` matters because the local catalog currently has at least one
`1970-01-01` episode date artifact. We should either clean those records or set explicit training
bounds for model jobs.

### Local One-Cutoff Experiment Scaffold

Before running the full rolling historical job, use a single cutoff with a balanced sample for local
feature/model exploration:

```bash
.venv/bin/python manage.py build_future_link_experiment_dataset \
  --output data/reports/future_link_experiment_dataset.csv \
  --negative-ratio 1 \
  --max-degree 3 \
  --horizon-days 90
```

This keeps all positive labels from the degree-3 candidate universe and deterministically samples
the same number of negatives. On the current local data this produced:

- Rows: 5,832
- Positives: 2,916
- Sampled negatives: 2,916
- Columns: 40 total, including 35 numeric feature columns
- Cutoff: `2026-02-18T04:32:00+00:00`
- Horizon end: `2026-05-19T04:32:00+00:00`

Train local experiment models:

```bash
.venv/bin/python manage.py train_future_link_experiment_model \
  --dataset data/reports/future_link_experiment_dataset.csv \
  --model-type xgboost
```

Initial balanced-holdout results:

| Model | Features | Average precision | ROC AUC | F1 at 0.5 |
| --- | ---: | ---: | ---: | ---: |
| Logistic regression | 35 | 0.903 | 0.900 | 0.818 |
| XGBoost | 35 | 0.912 | 0.908 | 0.823 |
| Logistic forward selection | 12 | 0.904 | 0.899 | 0.813 |
| XGBoost forward selection | 9 | 0.916 | 0.910 | 0.824 |

The XGBoost forward-selected features were:

- `shared_neighbor_score`
- `podcast_age_days`
- `guest_days_since_latest_appearance`
- `podcast_guest_count_365d`
- `podcast_guest_appearance_count`
- `podcast_repeat_guest_rate`
- `guest_repeat_appearance_rate`
- `guest_appearance_count_180d`
- `podcast_degree_proxy`

Important caveat: these metrics are for a balanced local exploration set. They tell us the feature
family has signal, but they do not replace evaluation on the real imbalanced candidate universe or
ranking metrics such as precision@K and NDCG@K.

### Full Imbalanced One-Cutoff Logistic Grid

For full-imbalance local experiments, materialize the selected 12-feature matrix once and reuse it
for hyperparameter search:

```bash
.venv/bin/python manage.py build_future_link_feature_matrix \
  --output-dir data/reports/future_link_full_matrix \
  --max-degree 3 \
  --horizon-days 90
```

This writes memory-mapped NumPy arrays rather than a giant CSV:

- `X.npy`: 12 `float32` features
- `y.npy`: labels
- `split.npy`: deterministic train/test split
- `metadata.json`: feature names and cutoff config

Current one-cutoff matrix:

- Rows: 23,725,479
- Positives: 2,916
- Train rows: 18,981,633
- Train positives: 2,344
- Test rows: 4,743,846
- Test positives: 572
- Matrix size on disk: about 1.1 GB

Grid command:

```bash
.venv/bin/python manage.py grid_search_future_link_logistic \
  --matrix-dir data/reports/future_link_full_matrix \
  --output data/reports/future_link_logistic_grid.json \
  --c-values 0.1,1,10 \
  --class-weights none,balanced,1000,3000,8000,12000
```

Best settings by selected metrics:

| Metric | Best class weight | C | Value |
| --- | --- | ---: | ---: |
| Average precision | none | 10 | 0.003534 |
| ROC AUC | 12000 | 0.1 | 0.889525 |
| Precision@100 | 1000 | 10 | 0.040000 |
| Precision@1000 | none | 10 | 0.019000 |
| Precision@5000 | none | 10 | 0.007800 |
| Recall at 0.5 threshold | 12000 | 10 | 0.872378 |

Takeaway: weighting the positive class improves threshold recall and ROC AUC, but the unweighted
model ranked better by average precision and precision@1000/5000 in this first grid. Since the
production use case is ranking recommendations, average precision and precision@K should matter
more than the default 0.5 threshold behavior.

## Candidate Generation

Generating every podcast-person non-edge is the biggest scalability risk. We should treat candidate
generation as a retrieval step, then ranking/modeling as a second step.

### Initial Degree-Limited Prototype

Prototype command:

```bash
.venv/bin/python manage.py build_future_link_candidates --max-degree 3 --horizon-days 90
```

Local snapshot result before the larger cloud data refresh:

- Cutoff: `2026-02-10T17:00:00+00:00`
- Label horizon: through `2026-05-11T17:00:00+00:00`
- Podcasts scored: 515
- Known guest people before cutoff: 73,797
- Historical guest links before cutoff: 118,266
- Future positive links in horizon: 7,980
- Candidate rows at max degree 3: 14,350,596
- Positive labels in candidates: 2,022
- Negative labels in candidates: 14,348,574
- Positive rate: 0.000141
- Negative:positive imbalance: 7,096.2:1
- Retrieval recall over eligible future positives: 0.405
- Future positives missed by degree retrieval: 2,970
- Future positives excluded as existing links: 2,987
- Future positives excluded as hosts: 1

Takeaway: degree-limited retrieval is much better than the full podcast-by-person cross product, but
degree 3 still creates millions of rows and severe class imbalance. We should use it as a candidate
source, not as the final training dataset without additional negative sampling or top-N retrieval
limits per podcast.

After pulling a larger cloud-shaped local dataset, the degree-3 baseline changed to:

- Cutoff: `2026-02-18T04:32:00+00:00`
- Label horizon: through `2026-05-19T04:32:00+00:00`
- Podcasts scored: 1,017
- Known guest people before cutoff: 103,290
- Historical guest links before cutoff: 164,066
- Future positive links in horizon: 11,346
- Candidate rows at max degree 3: 23,725,479
- Positive labels in candidates: 2,916
- Negative labels in candidates: 23,722,563
- Positive rate: 0.000123
- Negative:positive imbalance: 8,135.3:1
- Retrieval recall over eligible future positives: 0.384

The scored podcast count came from eligibility filtering on that refreshed local snapshot:

- Total podcasts: 1,180
- Active podcasts: 1,137
- Podcasts with any historical canonical link before cutoff: 1,065
- Active podcasts with historical canonical links before cutoff: 1,063
- Scored podcasts after requiring at least one historical guest link: 1,017
- Inactive podcasts with historical canonical links: 2
- Active podcasts without historical canonical links: 74

### Shared-Guest Heuristic Prototype

Prototype command:

```bash
.venv/bin/python manage.py build_future_link_candidates \
  --strategy shared-guest \
  --top-per-podcast 5000 \
  --min-shared-guests 1 \
  --compare-degree-baseline \
  --max-degree 3 \
  --horizon-days 90
```

The heuristic scores candidates through shared-guest podcast neighborhoods:

```text
target podcast -> prior target guest -> neighbor podcast -> candidate guest
```

Each neighbor podcast contributes its shared-guest count as retrieval score to its candidate guests.
This keeps the candidates deterministic and network-based while allowing a per-podcast cap.

Results compared with the 14,350,596-row degree-3 baseline:

| Heuristic | Rows | Positives | Row reduction | Positive retention | Positives lost |
| --- | ---: | ---: | ---: | ---: | ---: |
| top 5,000 per podcast, min 1 shared guest | 2,210,916 | 1,381 | 0.846 | 0.683 | 641 |
| top 10,000 per podcast, min 1 shared guest | 4,217,976 | 1,632 | 0.706 | 0.807 | 390 |
| no top cap, min 2 shared guests | 9,597,793 | 1,878 | 0.331 | 0.929 | 144 |

Takeaway: a top-N cap gives the biggest row reduction but discards meaningful positives. Requiring
stronger shared-neighbor evidence keeps more positives, but not enough row reduction by itself. A
good next pass is likely a hybrid, for example retaining all candidates with `min_shared_guests >= 2`
plus top-scored candidates from the `min_shared_guests = 1` pool.

After the larger cloud data refresh, results compared with the 23,725,479-row degree-3 baseline:

| Heuristic | Rows | Positives | Row reduction | Positive retention | Positives lost |
| --- | ---: | ---: | ---: | ---: | ---: |
| top 5,000 per podcast, min 1 shared guest | 4,138,208 | 1,999 | 0.826 | 0.686 | 917 |
| top 10,000 per podcast, min 1 shared guest | 7,587,595 | 2,312 | 0.680 | 0.793 | 604 |
| no top cap, min 2 shared guests | 13,709,272 | 2,647 | 0.422 | 0.908 | 269 |
| top 5,000, always keep score >= 3 | 12,230,393 | 2,652 | 0.485 | 0.909 | 264 |
| top 2,500, always keep score >= 3 | 11,479,378 | 2,625 | 0.516 | 0.900 | 291 |
| top 1,000, always keep score >= 3 | 11,072,339 | 2,600 | 0.533 | 0.892 | 316 |

The current best compromise is probably `top_per_podcast=2500` with `always_keep_score=3`: it keeps
about 90% of the degree-3 positives while removing about 52% of the rows. The stricter 1,000 cap
only removes another 407k rows but drops below 90% positive retention.

### Positive Rows

Always include all positive future links for each cutoff, subject to quality filters.

### Negative Rows

Use several negative sources, tagged with `negative_source`:

- Random negatives: sampled non-links across the active podcast/person universe.
- Hard negatives from nearby graph structure: people who share guests, hosts, categories, or network
  neighborhoods with the podcast but do not link in the horizon.
- Popular-person negatives: high-frequency guests who did not appear on the target podcast.
- Podcast-local negatives: candidate guests for a podcast from similar podcasts or same categories.

Suggested ratio for first training pass:

- 10-50 negatives per positive, stratified by cutoff and podcast.
- Keep a separate evaluation set with a larger candidate universe to estimate ranking behavior.

### Retrieval Candidates For Production Ranking

For weekly predictions, generate candidates from a union of:

- Guests who appeared on podcasts with shared guests.
- Guests who appeared on podcasts sharing category metadata.
- Guests within two hops of the podcast's hosts or recent guests in the people graph.
- Globally active guests in the last 6-12 months.
- Guests with strong historical repeat behavior across the network.

Keep the candidate universe bounded per podcast, for example top 1,000-10,000 candidates before
model scoring.

## Feature Ideas

### Podcast Features

- Total guest appearances before cutoff.
- Unique guests before cutoff.
- Repeat-guest rate.
- Average days between episodes or guest episodes.
- Recent episode count: 30/90/180/365 days.
- Recent guest count: 30/90/180/365 days.
- Active flag and interview-podcast flag.
- Category metadata and category concentration.
- Podcast age at cutoff.
- Time since latest published episode.
- Network metrics at cutoff: degree, closeness, betweenness, shared-guest edges.

### Guest Features

- Total guest appearances before cutoff.
- Unique podcasts appeared on before cutoff.
- Repeat-appearance rate across all podcasts.
- Recent guest appearances: 30/90/180/365 days.
- Recent unique podcasts: 30/90/180/365 days.
- Time since latest guest appearance.
- First-seen age and activity trend.
- Network metrics at cutoff: PageRank, hub, authority, degree, closeness, betweenness.

### Podcast-Guest Pair Features

- Has the guest appeared on the podcast before cutoff? This should be false by construction, but keep
  as an assertion/debug field.
- Guest appearance frequency by the guest globally.
- Guest appearance frequency on the given podcast's neighborhood.
- Podcast guest frequency: how often the given podcast books guests overall and recently.
- Category overlap between guest's historical podcast categories and target podcast categories.
- Shared-neighborhood counts: number of target podcast guests who have appeared with the candidate.
- Weighted shared-neighborhood counts using episode counts or durations when available.
- Host overlap features: candidate's overlap with hosts' prior guest networks.
- Recency-weighted versions of shared-neighborhood and host-overlap features.
- Two-hop paths from podcast to guest and path counts.
- Resource allocation, Adamic-Adar, Jaccard, preferential attachment, and community-aware variants.
- Similar-podcast features: candidate has appeared on top-N podcasts similar to the target podcast.

### Temporal Features

- Month and quarter of cutoff.
- Podcast-specific seasonality if enough history exists.
- Guest-specific recent momentum: recent appearances divided by historical baseline.
- Podcast booking momentum: recent guest activity divided by historical baseline.

### Quality And Confidence Features

- Minimum/average extraction confidence for the guest's appearances.
- Entity-resolution match probability summary.
- Whether the canonical person has aliases or likely ambiguous names.
- Count of observations backing the canonical entity.

## Leakage Rules

Every feature must be computed using only data before the cutoff. This includes:

- Network metrics.
- Category/top-podcast summaries for people.
- Podcast activity statistics.
- Guest frequency features.
- Entity metadata if it depends on future observations, such as `observation_count` and
  `last_seen_at`.

Prefer feature builders that accept `cutoff_at` directly and query only pre-cutoff rows.

## Train/Test Splitting

Use temporal evaluation as the main truth:

- Train on earlier cutoffs.
- Validate on later cutoffs.
- Test on the latest held-out block of cutoffs.

To reduce bias from repeated rows and superstar guests/podcasts:

- Report metrics by cutoff date.
- Report macro averages by podcast, not only row-weighted global metrics.
- Consider group-aware analysis by podcast and by guest.
- Consider a final stress test that holds out entire podcasts, categories, or guests, even if that
  is harder than the intended production task.

Do not randomly split rows across all date cuts for the primary evaluation. That would leak too much
information from adjacent windows.

## Metrics

This is a ranking problem with rare positives, not a balanced classification problem.

Primary metrics:

- Precision@K per podcast.
- Recall@K per cutoff.
- Mean average precision.
- NDCG@K.
- PR AUC for global discrimination.

Secondary metrics:

- ROC AUC for comparability with older work.
- Calibration by score bucket.
- Hit rate among top 10/25/100 candidates per podcast.
- Coverage: number of podcasts with at least one viable recommendation.

Track metric evolution over time:

- One row per cutoff.
- Global and macro-by-podcast metrics.
- Positive count, candidate count, and base rate per cutoff.
- Model version, feature version, candidate-generation config, train window, horizon.

## Cloud Job Shape

Feature engineering and training should run in cloud jobs, not local development.

Suggested pipeline stages:

1. Build date cuts and candidate rows.
2. Materialize pre-cutoff aggregate tables/features.
3. Join features into a training dataset.
4. Train model and tune hyperparameters.
5. Evaluate by cutoff and write metrics/artifacts.
6. Score current production candidates.

Storage options:

- Database tables for smaller feature/candidate manifests and score outputs.
- Object storage for large Parquet datasets and model artifacts.
- JSON metadata for run configs and reproducibility.

Model options:

- Start with logistic regression or HistGradientBoosting as a sanity baseline.
- Use XGBoost once the dataset and feature builders are stable.
- Keep a simple popularity/similarity baseline for every evaluation report.

## Proposed Tables Or Artifacts

Possible Django models or external tables:

- `FutureLinkPredictionRun`: model version, feature version, candidate config, horizon, status.
- `FutureLinkTrainingCutoff`: cutoff date, horizon, counts, split assignment.
- `FutureLinkCandidate`: cutoff, podcast, canonical, label, candidate source metadata.
- `FutureLinkScore`: run, cutoff/scored_at, podcast, canonical, score, rank, feature snapshot hash.
- `FutureLinkMetric`: run, cutoff, metric name, metric value, segment.

If row counts are too large for Django-managed tables, keep full candidates/features in Parquet and
store only manifests, metrics, and latest scores in Postgres.

## Implementation Plan

### Phase 1: Design And Baselines

- Port the legacy feature inventory into current entity IDs.
- Add a small local prototype command that builds one cutoff with bounded negative sampling.
- Verify labels against `PersonEntityLink` and `Episode.published_at`.
- Establish baseline metrics with popularity and similar-podcast retrieval.

### Phase 2: Scalable Candidate/Feature Builder

- Add candidate-generation strategies with source tags.
- Build pre-cutoff aggregate feature queries.
- Avoid per-row networkx calls where possible; precompute dictionaries and sparse matrices.
- Write datasets as Parquet in cloud storage.

### Phase 3: Training And Evaluation

- Add cloud job command for rolling cutoffs.
- Train baseline and XGBoost models.
- Produce per-cutoff metric evolution artifacts.
- Compare against simple baselines.

One-cut model follow-up:

- The online SGD approximation used for the first cloud rolling run produced pathological scores:
  the top 1,000 current predictions all scored 1.0 and historical one-cut AP fell well below exact
  logistic regression.
- Exact logistic regression on the one-cut full imbalanced matrix is the better local baseline:
  `C=10`, no class weight had the best AP and P@1000/P@5000 in the grid, while `class_weight=1000`
  only improved P@100 slightly.
- Weighted logistic scores can be prior-corrected by subtracting `log(positive_weight)` from the
  logit, but the unweighted exact LR has cleaner calibration metrics on the one-cut holdout.
- Current scoring with the exact one-cut LR produced a much healthier top-1,000 score range
  instead of all-1.0 scores, and reduced top-list concentration from two dominant podcasts to a
  broader group.

### Phase 4: Production Scoring

- Score current candidates after weekly ingestion/extraction/metrics jobs.
- Store top-ranked recommendations, initially only the global top 1,000 podcast/person pairs.
- Keep scoring streaming: build candidates from the current network, score feature batches with the
  trained model, and maintain a top-N heap instead of persisting the full current candidate table.
- Write prediction runs to Postgres with the scored-at timestamp, model URI, candidate config,
  total candidates scored, top ranks, scores, display names, and feature snapshots for explanation.
- Store score-distribution summaries in Postgres for the full streamed candidate population, not
  just the retained top-N rows. A fixed-bin histogram is enough for the UI and avoids writing every
  scored pair.
- Compare the full-candidate score distribution with later observed new podcast/guest links that
  had a prior score. The UI should render this as a traditional two-population histogram using
  normalized densities, while still showing raw counts on hover or in metadata.
- Define "new links" for the weekly audit as podcast/guest links whose first source episode was
  published in the most recent weekly episode window. The scoring snapshot should use only links
  published before that window begins.
- Exclude podcast/guest pairs that already existed before the weekly window. Repeat guest
  appearances are useful for other analyses, but they are not positives for this first-time link
  prediction task.
- The weekly update pipeline runs the future-link audit and current top-N scoring after ingestion,
  extraction, person entity resolution, and network metric refresh.
- Do not use CSV/JSON artifacts for the production predictions page. The page should read
  `FutureLinkPredictionRun`, `FutureLinkPrediction`, `FutureLinkWeeklyAuditRun`, and
  `FutureLinkWeeklyAuditLink` rows from Postgres.
- Add explorer UI surfaces only after offline evaluation is credible.

### Phase 5: Performance Story In The UI

Once the model is producing weekly/current scores, add a performance-oriented page section that shows
how the model is doing in concrete recent cases:

- Recent new podcast-guest links from the latest ingestion windows.
- For each new link, whether it had been scored before the link happened.
- The model score and rank of that eventual link within the podcast's candidate list.
- A list/table of recent hits with podcast, guest, score, rank, episode date, and prediction date.
- A histogram of scores for recent true new links.
- A comparison histogram for the general scored candidate population from the same prediction run.
- Optional score percentile for each new link so the page can say, for example, "this new link was
  in the top 2% of candidates for that podcast."

This should make the prediction system more legible than aggregate metrics alone: visitors can see
both the time-series performance and the actual links the model was close to anticipating.

## Open Questions

- Should repeated guest appearances on the same podcast be excluded from prediction, or should a
  second task predict repeat bookings?
- Should the label require a high-confidence guest extraction, or include lower-confidence
  appearances with confidence as label weight?
- What minimum history should a podcast need before we score it?
- Should inactive podcasts be excluded entirely or retained for historical training windows where
  they were active?
- How should we represent categories for canonical people when category history is induced from
  podcasts they appeared on?
- How large should the production candidate set be per podcast before scoring?
- Do we need separate models by podcast category or podcast size once we have enough data?
