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

Create secrets:

```bash
printf 'REPLACE_ME' | gcloud secrets create django-secret-key --data-file=-
printf 'REPLACE_ME' | gcloud secrets create openai-api-key --data-file=-
printf 'REPLACE_ME' | gcloud secrets create database-url --data-file=-
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
  --add-cloudsql-instances PROJECT_ID:us-central1:podcast-network-db \
  --set-secrets DATABASE_URL=database-url:latest,DJANGO_SECRET_KEY=django-secret-key:latest,OPENAI_API_KEY=openai-api-key:latest \
  --command python \
  --args manage.py,run_weekly_update_pipeline
```

The heavy historical backfills should become separate jobs with explicit limits, not part of
the regular web service startup.
