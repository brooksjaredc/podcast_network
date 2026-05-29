PYTHON ?= python
MANAGE ?= $(PYTHON) manage.py
GCP_PROJECT ?= podcast-network-prod
GCP_REGION ?= us-central1
CLOUD_SQL_INSTANCE ?= podcast-network-db
CLOUD_RUN_SERVICE ?= podcast-network-web
IMAGE ?= us-central1-docker.pkg.dev/$(GCP_PROJECT)/podcast-network/web:latest
CUSTOM_DOMAIN ?=
DJANGO_ALLOWED_HOSTS ?= .run.app$(if $(CUSTOM_DOMAIN),$(comma)$(CUSTOM_DOMAIN),)
DJANGO_CSRF_TRUSTED_ORIGINS ?= $(if $(CUSTOM_DOMAIN),https://$(CUSTOM_DOMAIN),)
comma := ,

.PHONY: install dev migrate test lint check preflight cloud-sql-proxy sync-cloud-db cloud-status deploy

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

preflight:
	$(MANAGE) production_preflight

cloud-sql-proxy:
	cloud-sql-proxy --gcloud-auth $(GCP_PROJECT):$(GCP_REGION):$(CLOUD_SQL_INSTANCE) --port 5433

sync-cloud-db:
	scripts/sync_cloud_db.sh

cloud-status:
	gcloud run services describe $(CLOUD_RUN_SERVICE) --project $(GCP_PROJECT) --region $(GCP_REGION)

deploy:
	gcloud builds submit --project $(GCP_PROJECT) --tag $(IMAGE)
	gcloud run deploy $(CLOUD_RUN_SERVICE) \
		--project $(GCP_PROJECT) \
		--region $(GCP_REGION) \
		--image $(IMAGE) \
		--add-cloudsql-instances $(GCP_PROJECT):$(GCP_REGION):$(CLOUD_SQL_INSTANCE) \
		--set-env-vars "^|^DJANGO_DEBUG=false|DJANGO_ALLOWED_HOSTS=$(DJANGO_ALLOWED_HOSTS)|DJANGO_CSRF_TRUSTED_ORIGINS=$(DJANGO_CSRF_TRUSTED_ORIGINS)|DJANGO_SECURE_SSL_REDIRECT=true" \
		--set-secrets DATABASE_URL=database-url:latest,DJANGO_SECRET_KEY=django-secret-key:latest,OPENAI_API_KEY=openai-api-key:latest \
		--allow-unauthenticated
