# Google Cloud Deployment Notes

## Accounts And Services

1. Create or use a Google account for Google Cloud.
2. Create a Google Cloud project, for example `podcast-network-prod`.
3. Attach a billing account to the project.
4. Install and initialize the Google Cloud CLI:

```bash
gcloud init
gcloud config set project PROJECT_ID
gcloud config set run/region us-central1
```

5. Enable the core APIs:

```bash
gcloud services enable \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  run.googleapis.com \
  sqladmin.googleapis.com \
  secretmanager.googleapis.com \
  cloudscheduler.googleapis.com \
  storage.googleapis.com
```

## First Cloud Resources

Create an Artifact Registry repository for container images:

```bash
gcloud artifacts repositories create podcast-network \
  --repository-format=docker \
  --location=us-central1
```

Create a Cloud SQL PostgreSQL instance and database:

```bash
gcloud sql instances create podcast-network-db \
  --database-version=POSTGRES_16 \
  --region=us-central1 \
  --tier=db-custom-1-3840 \
  --storage-size=50GB

gcloud sql databases create podcast_network --instance=podcast-network-db
gcloud sql users create podcast_app --instance=podcast-network-db --password='REPLACE_ME'
```

Create a Cloud Storage bucket for generated artifacts:

```bash
gcloud storage buckets create gs://PROJECT_ID-podcast-network-artifacts \
  --location=us-central1
```

Use stable prefixes in that bucket for generated artifacts and raw ingestion snapshots:

```text
gs://PROJECT_ID-podcast-network-artifacts/static-plots/latest
gs://PROJECT_ID-podcast-network-artifacts/raw-feed-snapshots
gs://PROJECT_ID-podcast-network-artifacts/openai-batches
```

Create secrets:

```bash
printf 'REPLACE_ME' | gcloud secrets create django-secret-key --data-file=-
printf 'REPLACE_ME' | gcloud secrets create openai-api-key --data-file=-
printf 'REPLACE_ME' | gcloud secrets create database-url --data-file=-
# Optional generic JSON webhook used by send_weekly_update_alert.
printf 'REPLACE_ME' | gcloud secrets create weekly-update-alert-webhook-url --data-file=-
```

For Cloud SQL Unix sockets, `DATABASE_URL` should look like:

```text
postgresql://podcast_app:DB_PASSWORD@/podcast_network?host=/cloudsql/PROJECT_ID:us-central1:podcast-network-db
```

## Build And Deploy

Build and push the image:

```bash
gcloud builds submit \
  --tag us-central1-docker.pkg.dev/PROJECT_ID/podcast-network/web:latest
```

Deploy the web service:

```bash
gcloud run deploy podcast-network-web \
  --image us-central1-docker.pkg.dev/PROJECT_ID/podcast-network/web:latest \
  --region us-central1 \
  --add-cloudsql-instances PROJECT_ID:us-central1:podcast-network-db \
  --set-env-vars DJANGO_DEBUG=false,DJANGO_ALLOWED_HOSTS=.run.app,DJANGO_SECURE_SSL_REDIRECT=true \
  --set-secrets DATABASE_URL=database-url:latest,DJANGO_SECRET_KEY=django-secret-key:latest,OPENAI_API_KEY=openai-api-key:latest
```

## Jobs

Use the same image for management-command jobs. Example:

```bash
gcloud run jobs create weekly-update \
  --image us-central1-docker.pkg.dev/PROJECT_ID/podcast-network/web:latest \
  --region us-central1 \
  --set-cloudsql-instances PROJECT_ID:us-central1:podcast-network-db \
  --set-env-vars PODCAST_NETWORK_RAW_SNAPSHOT_GCS_URI=gs://PROJECT_ID-podcast-network-artifacts/raw-feed-snapshots,PODCAST_NETWORK_BATCH_ARTIFACT_GCS_URI=gs://PROJECT_ID-podcast-network-artifacts/openai-batches \
  --set-secrets DATABASE_URL=database-url:latest,DJANGO_SECRET_KEY=django-secret-key:latest,OPENAI_API_KEY=openai-api-key:latest,PODCAST_NETWORK_WEEKLY_UPDATE_ALERT_WEBHOOK_URL=weekly-update-alert-webhook-url:latest \
  --command python \
  --args manage.py,run_weekly_update_pipeline \
  --task-timeout 86400 \
  --memory 2Gi \
  --cpu 1
```

Before scheduling the job, run the command in dry-run mode and then with tight limits:

```bash
gcloud run jobs execute weekly-update \
  --region us-central1 \
  --args manage.py,production_preflight,--require-postgres,--require-production-settings,--require-gcs-artifacts,--future-link-gcs-model-uri,gs://PROJECT_ID-podcast-network-artifacts/future-link-training/MODEL/future_link_online_logistic.joblib

gcloud run jobs execute weekly-update \
  --region us-central1 \
  --args manage.py,run_weekly_update_pipeline,--dry-run

gcloud run jobs execute weekly-update \
  --region us-central1 \
  --args manage.py,run_weekly_update_pipeline,--first-pass-batch-size,25,--max-first-pass-batches,1,--evolution-max-weeks,1
```

The regular weekly job is meant for incremental updates. Heavy historical backfills should
remain separate jobs with explicit limits, not part of the regular web service startup.

The Cloud Workflow runs `production_preflight` before scraping and
`weekly_update_status --fail-on-problem` after predictions. A failure in either command
fails the workflow execution instead of leaving the issue hidden in logs.
It also calls `send_weekly_update_alert` after success or failure. You can pass
`alert_webhook_url` as a workflow argument or configure
`PODCAST_NETWORK_WEEKLY_UPDATE_ALERT_WEBHOOK_URL` on the alert/status Cloud Run job.

To persist raw RSS snapshots from Cloud Run, pass `--raw-snapshot-storage gcs` to the
scrape phase or weekly coordinator. The snapshot rows in Postgres will then point at
immutable `gs://` objects instead of local or noop paths.

To persist OpenAI Batch API JSONL artifacts, set `PODCAST_NETWORK_BATCH_ARTIFACT_GCS_URI`
or pass `--batch-artifact-gcs-uri`. Extraction run metadata will keep both the local
temporary path and durable `input_jsonl_gcs_uri`, `output_jsonl_gcs_uri`, and optional
`error_jsonl_gcs_uri` values.

Future-link prediction/audit runs record model artifact `model_sha256`,
`model_size_bytes`, and the current `git_sha` in run metadata. Trained person-entity
candidate scoring stores the same model checksum fields in candidate pair features.

Destructive management-command options such as `sync_guest_appearances --clear`,
`generate_person_entity_candidates --clear`, and the default truncating mode of
`copy_sqlite_to_postgres` require `--confirm-destructive` when running against Postgres.
For one-off controlled automation, `PODCAST_NETWORK_ALLOW_DESTRUCTIVE=true` can also
provide that confirmation.

Heavy management commands support `--statement-timeout-ms` to set a Postgres
`statement_timeout` for the duration of the command. The default `0` leaves the
connection unchanged.
