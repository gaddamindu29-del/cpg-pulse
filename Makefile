.PHONY: help setup up down logs seed generate-data generate-data-sample \
        test test-unit test-integration test-dq lint dbt-run dbt-test dbt-docs \
        api dashboard clean clean-data ps

help:
	@echo "CPG Pulse -- common commands"
	@echo "  make setup                 Create .env from .env.example, install Python deps"
	@echo "  make up                    Start Postgres + MinIO + Airflow (docker compose)"
	@echo "  make down                  Stop and remove containers (data volumes persist)"
	@echo "  make logs                  Tail logs for all services"
	@echo "  make seed                  Apply metadata schema + create MinIO buckets (idempotent)"
	@echo "  make generate-data         Generate the full synthetic dataset into data/generated/"
	@echo "  make generate-data-sample  Generate a small dataset quickly (for a fast smoke test)"
	@echo "  make test                  Run the full pytest suite"
	@echo "  make test-unit             Run unit tests only"
	@echo "  make test-integration      Run integration tests only"
	@echo "  make test-dq               Run data-quality tests only"
	@echo "  make lint                  Run ruff over the Python codebase"
	@echo "  make dbt-run               Run dbt models against the local Postgres warehouse"
	@echo "  make dbt-test              Run dbt tests"
	@echo "  make dbt-docs              Generate and serve dbt docs"
	@echo "  make api                   Run the FastAPI service locally (uvicorn, reload)"
	@echo "  make dashboard             Run the Streamlit dashboard locally"
	@echo "  make clean-data            Remove data/generated/ and data/quarantine/ contents"
	@echo "  make clean                 clean-data + stop containers + remove volumes (DESTRUCTIVE)"

setup:
	@if [ ! -f .env ]; then cp .env.example .env && echo "Created .env from .env.example"; fi
	pip install -r requirements.txt

up:
	docker compose up -d --build
	@echo "Airflow UI:   http://localhost:8080  (admin/admin by default)"
	@echo "MinIO console: http://localhost:9001 (see .env for credentials)"

down:
	docker compose down

ps:
	docker compose ps

logs:
	docker compose logs -f

seed:
	python scripts/seed_local_environment.py

generate-data:
	python scripts/generate_synthetic_data.py

generate-data-sample:
	python scripts/generate_synthetic_data.py \
		--start-date 2025-01-01 --end-date 2025-02-28 \
		--num-products 12 --stores-per-retailer "RTL-WMT=3,RTL-TGT=2,RTL-KRG=2,RTL-AMZ=1" \
		--output-dir data/sample

test:
	pytest tests/ api/tests/ -v

test-unit:
	pytest tests/unit/ -v

test-integration:
	pytest tests/integration/ -v

test-dq:
	pytest tests/data_quality/ -v

lint:
	ruff check scripts/ ingestion/ spark/ api/ dashboard/ tests/

# Order matters: dim_product_snapshot/dim_store_snapshot select from the
# staging models (ref('stg_product_master')/ref('stg_store_master')), not
# the raw source, so staging must be built before `dbt snapshot` runs --
# see docs/remaining_work.md architectural decision #2. Running plain
# `dbt run` (or `dbt snapshot` before any `dbt run`) on a fresh database
# fails with "relation staging.stg_store_master does not exist".
dbt-run:
	cd dbt && dbt seed --target local
	cd dbt && dbt run --select staging --target local
	cd dbt && dbt snapshot --target local
	cd dbt && dbt run --exclude staging --target local

dbt-test:
	cd dbt && dbt test --target local

dbt-docs:
	cd dbt && dbt docs generate --target local && dbt docs serve --target local

api:
	uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

dashboard:
	streamlit run dashboard/app.py

clean-data:
	rm -rf data/generated/* data/quarantine/*
	@touch data/quarantine/.gitkeep

clean: clean-data
	docker compose down -v
