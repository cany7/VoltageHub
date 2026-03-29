.PHONY: up down build backfill dbt-build dbt-docs dbt-deps lint terraform-init terraform-apply terraform-destroy clean

AIRFLOW_SERVICE ?= airflow-webserver
AIRFLOW_DAG_ID ?= eia_grid_batch
DBT_PROJECT_DIR ?= /opt/airflow/dbt
DBT_PROFILES_DIR ?= /opt/airflow/dbt
DBT_TARGET ?= dev
TERRAFORM_DIR ?= terraform
TERRAFORM_VAR_FILE ?= terraform.tfvars

DOCKER_COMPOSE := docker compose -f docker/docker-compose.yml

ifdef BATCH_DATE
DBT_VARS := --vars '{"batch_date": "$(BATCH_DATE)"}'
endif

up:
	$(DOCKER_COMPOSE) up -d

down:
	$(DOCKER_COMPOSE) down

build:
	$(DOCKER_COMPOSE) build

backfill:
	@# Assumption: callers provide an explicit UTC backfill window so Makefile usage
	@# stays deterministic across shells and environments.
	@test -n "$(START_DATE)" || (echo "START_DATE is required, e.g. 2026-03-27T00:00:00+00:00" && exit 1)
	@test -n "$(END_DATE)" || (echo "END_DATE is required, e.g. 2026-03-28T00:00:00+00:00" && exit 1)
	$(DOCKER_COMPOSE) exec $(AIRFLOW_SERVICE) airflow dags backfill $(AIRFLOW_DAG_ID) --start-date "$(START_DATE)" --end-date "$(END_DATE)"

dbt-deps:
	$(DOCKER_COMPOSE) exec $(AIRFLOW_SERVICE) dbt deps --project-dir $(DBT_PROJECT_DIR) --profiles-dir $(DBT_PROFILES_DIR)

dbt-build: dbt-deps
	$(DOCKER_COMPOSE) exec $(AIRFLOW_SERVICE) dbt build --project-dir $(DBT_PROJECT_DIR) --profiles-dir $(DBT_PROFILES_DIR) --target $(DBT_TARGET) $(DBT_VARS)

dbt-docs: dbt-deps
	$(DOCKER_COMPOSE) exec $(AIRFLOW_SERVICE) dbt docs generate --project-dir $(DBT_PROJECT_DIR) --profiles-dir $(DBT_PROFILES_DIR) --target $(DBT_TARGET)

lint:
	uv run ruff check .
	set -a; . ./.env; export GCP_SERVICE_ACCOUNT_KEY_PATH=./keys/service-account.json; export GOOGLE_APPLICATION_CREDENTIALS=./keys/service-account.json; export UV_CACHE_DIR=/tmp/uv-cache; set +a; uv run --with 'dbt-core==1.8.*' --with 'dbt-bigquery==1.8.*' sqlfluff lint --config sqlfluff_libs/.sqlfluff dbt/models

terraform-init:
	terraform -chdir=$(TERRAFORM_DIR) init

terraform-apply:
	terraform -chdir=$(TERRAFORM_DIR) apply -var-file=$(TERRAFORM_VAR_FILE)

terraform-destroy:
	terraform -chdir=$(TERRAFORM_DIR) destroy -var-file=$(TERRAFORM_VAR_FILE)

clean:
	rm -rf dbt/target dbt/dbt_packages .pytest_cache .ruff_cache
