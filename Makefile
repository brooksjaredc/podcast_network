PYTHON ?= python
MANAGE ?= $(PYTHON) manage.py
GCP_PROJECT ?= podcast-network-prod
GCP_REGION ?= us-central1
CLOUD_SQL_INSTANCE ?= podcast-network-db
CLOUD_RUN_SERVICE ?= podcast-network-web
IMAGE ?= us-central1-docker.pkg.dev/$(GCP_PROJECT)/podcast-network/web:latest

.PHONY: install dev migrate test lint check cloud-sql-proxy cloud-status deploy

install:
	python3.13 -m venv .venv
	. .venv/bin/activate && pip install -e ".[dev]"

dev:
	$(MANAGE) runserver

migrate:
	$(MANAGE) migrate

test:
	pytest

lint:
	ruff check

check: lint test

cloud-sql-proxy:
	cloud-sql-proxy $(GCP_PROJECT):$(GCP_REGION):$(CLOUD_SQL_INSTANCE) --port 5433

cloud-status:
	gcloud run services describe $(CLOUD_RUN_SERVICE) --project $(GCP_PROJECT) --region $(GCP_REGION)

deploy:
	gcloud builds submit --project $(GCP_PROJECT) --tag $(IMAGE)
	gcloud run deploy $(CLOUD_RUN_SERVICE) \
		--project $(GCP_PROJECT) \
		--region $(GCP_REGION) \
		--image $(IMAGE) \
		--add-cloudsql-instances $(GCP_PROJECT):$(GCP_REGION):$(CLOUD_SQL_INSTANCE) \
		--set-env-vars DJANGO_DEBUG=false,DJANGO_ALLOWED_HOSTS=.run.app,DJANGO_SECURE_SSL_REDIRECT=true \
		--set-secrets DATABASE_URL=database-url:latest,DJANGO_SECRET_KEY=django-secret-key:latest,OPENAI_API_KEY=openai-api-key:latest \
		--allow-unauthenticated
