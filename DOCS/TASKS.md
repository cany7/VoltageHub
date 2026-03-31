# TASKS.md — VoltageHub

---

## Implementation Phases

Development follows the order prescribed by the SPEC (Section 19). Each phase unlocks the next. MVP is Phases 1–3. Phase 4 is operational polish.

---

## Phase 1: Infrastructure and ELT Backbone

> **Goal:** Provision cloud resources, containerize Airflow, build the extraction pipeline, and land raw data in GCS and BigQuery.

### 1.1 Terraform Infrastructure

- [x] Create `terraform/variables.tf` with variables: `project_id`, `region`, `bucket_name`, BQ dataset names (`raw`, `staging`, `marts`, `meta`)
- [x] Create `terraform/main.tf`:
  - GCS bucket for raw landing zone
  - BigQuery datasets: `raw`, `staging`, `marts`, `meta`
  - Service account with IAM roles: `bigquery.dataEditor`, `bigquery.jobUser`, `storage.objectAdmin`
- [x] Create `terraform/outputs.tf` with bucket name, dataset IDs, service account email
- [x] Create `terraform/terraform.tfvars.example` with placeholder values
- [x] Verify: `terraform init && terraform plan` succeeds without errors
- [x] Verify: `terraform apply` provisions all resources; `terraform destroy` cleans up

**Acceptance:** All GCP resources exist after apply; no resources remain after destroy.

### 1.2 Docker Compose and Airflow Setup

- [x] Create `docker/Dockerfile` extending `apache/airflow:2.9.3-python3.11` with `dbt-core==1.8.*`, `dbt-bigquery==1.8.*`, `google-cloud-bigquery`, `google-cloud-storage`, `requests`
- [x] Create `docker-compose.yml` with services: `airflow-webserver`, `airflow-scheduler`, `postgres`
  - Mount `./airflow/dags`, `./airflow/plugins`, `./dbt` into Airflow containers
  - Use `LocalExecutor`
  - Reference `.env` file via `env_file`
- [x] Create `.env.example` with all required environment variables (see SPEC Section 5.2). Use `PORT` (not `SERVER_PORT`) for the serving API port. Use `GCS_BUCKET_NAME` as the canonical bucket config name.
- [x] Create `.gitignore` including `keys/*.json`, `.env`, `terraform.tfstate*`
- [x] Verify: `docker compose up -d` starts all services; Airflow UI responds at `localhost:8080`
- [x] Verify: `dbt deps` runs successfully inside the container

**Acceptance:** Airflow health endpoint responds; dbt is available inside the container.

### 1.3 EIA Data Extraction

- [x] Implement `extract_grid_batch` function:
  - Accepts `data_interval_start` and `data_interval_end` as parameters
  - Calls EIA API with time window parameters
  - Implements retry logic: 429 → exponential backoff (base 60s, max 3), 5xx → 3 retries with 2-min backoff, timeout → connection 120s, read 300s
  - Validates response structure; fails task on empty/malformed response
  - Returns raw response payload
- [x] Implement `land_raw_to_gcs` function:
  - Uploads raw JSON to `gs://<bucket>/voltage-hub/raw/year=YYYY/month=MM/day=DD/window=<start_iso>/batch.json`
- [x] Implement `load_to_bq_raw` function:
  - Uses `bigquery.Client.load_table_from_uri()` with `WRITE_TRUNCATE` on `batch_date` partition
  - Uses explicit schema from `airflow/schemas/raw_eia_batch.json`
- [x] Create `airflow/schemas/raw_eia_batch.json` with explicit BigQuery schema matching SPEC Section 10.2

**Acceptance:** A single time window extraction lands data in GCS at the correct path and loads into `raw.eia_grid_batch` with correct schema.

### 1.4 Airflow DAG

- [x] Create `airflow/dags/eia_grid_batch.py`:
  - Schedule: `@hourly` (configurable)
  - `catchup=True`, `max_active_runs=1`
  - Start date: configurable (default 7 days ago)
  - Retries: 2, delay 5 min, dagrun timeout: 2 hours
  - Task sequence: `extract_grid_batch` → `land_raw_to_gcs` → `load_to_bq_raw` → `dbt_source_freshness` → `dbt_build` → `check_anomalies` → `record_run_metrics` → `update_pipeline_state`
  - Operators: `PythonOperator` for extract/land/load/anomalies/metrics/state; `BashOperator` for dbt commands
  - Timeouts per task as specified in SPEC Section 13
- [x] Verify: DAG appears in Airflow UI without import errors
- [x] Verify: manual trigger completes full task chain

**Acceptance:** End-to-end DAG run completes; raw data in GCS and BigQuery.

### 1.5 dbt Models — Staging Layer

- [x] Create `dbt/dbt_project.yml` with project config
- [x] Create `dbt/packages.yml` with `dbt-labs/dbt_utils` (>=1.0.0, <2.0.0)
- [x] Create `dbt/profiles.yml` with `dev` and `ci` targets (see SPEC Section 16)
- [x] Create `dbt/models/staging/stg_grid_metrics.sql`:
  - Materialization: `incremental` with `insert_overwrite` on `observation_date`
  - Fields: `metric_surrogate_key`, `region`, `region_name`, `observation_timestamp`, `observation_date`, `metric_name`, `metric_value`, `energy_source`, `unit`, `_ingestion_timestamp`
  - Surrogate key: `dbt_utils.generate_surrogate_key(['region', 'observation_timestamp', 'metric_name', 'energy_source'])`
  - `is_incremental()` filter restricts source scan to affected dates
- [x] Create `dbt/models/staging/schema.yml` with column descriptions and tests:
  - `not_null` on `metric_surrogate_key`, `observation_timestamp`, `region`, `metric_name`, `metric_value`
  - `unique` on `metric_surrogate_key`
  - `accepted_values` on `metric_name`
- [x] Create `sources.yml` defining `raw.eia_grid_batch`
- [x] Verify: `dbt build` transforms raw data into `staging.stg_grid_metrics`

**Acceptance:** Staging table contains canonicalized rows; all dbt tests pass.

### 1.6 dbt Models — Marts Layer

- [x] Create `dbt/models/marts/core/fct_grid_metrics.sql`:
  - `incremental` with `insert_overwrite` on `observation_date`
  - One row per (region × observation_timestamp × metric_name × energy_source)
  - Clustered by `region`, `metric_name`
- [x] Create `dbt/models/marts/core/dim_region.sql`:
  - `incremental` with `merge` on `region` (unique_key)
  - Fields: `region` (PK), `region_name`
- [x] Create `dbt/models/marts/core/dim_energy_source.sql`:
  - `incremental` with `merge` on `energy_source` (unique_key)
  - Fields: `energy_source` (PK), optional category grouping
- [x] Create `dbt/models/marts/core/schema.yml` with descriptions and tests:
  - `relationships` on `fct_grid_metrics.region` → `dim_region.region`
  - `relationships` on `fct_grid_metrics.energy_source` → `dim_energy_source.energy_source`
- [x] Create `dbt/models/marts/aggregates/agg_load_hourly.sql` — hourly load by region (full rebuild)
- [x] Create `dbt/models/marts/aggregates/agg_load_daily.sql` — daily load by region: avg, min, max, total (full rebuild)
- [x] Create `dbt/models/marts/aggregates/agg_generation_mix.sql` — generation by region × observation_date × energy_source (full rebuild)
- [x] Create `dbt/models/marts/aggregates/agg_top_regions.sql` — daily ranked regions by total load (full rebuild). Output columns: `observation_date`, `region`, `region_name`, `daily_total_load` (FLOAT64), `rank` (INT64, 1 = highest load per date)
- [x] Create `dbt/models/marts/aggregates/schema.yml` with descriptions
- [x] Verify: `dbt build` populates all mart and aggregate tables

**Acceptance:** Mart fact/dimension/aggregate tables populated; relationship tests pass.

### 1.7 Makefile

- [x] Create `Makefile` with targets: `up`, `down`, `build`, `backfill`, `dbt-build`, `dbt-docs`, `dbt-deps`, `lint`, `terraform-init`, `terraform-apply`, `terraform-destroy`, `clean`
- [x] Verify: each make target runs the expected command

---

## Phase 2: Meta Layer, Freshness, and Anomaly Detection

> **Goal:** Build the control plane — pipeline state tracking, freshness monitoring, anomaly detection, and run metrics.

### 2.1 Meta Tables Schema

- [x] Create `dbt/models/meta/schema.yml` defining meta table schemas:
  - `meta.pipeline_state`: `pipeline_name`, `last_successful_window_start`, `last_successful_window_end`, `last_successful_run_id`, `updated_at`
  - `meta.run_metrics`: `run_id`, `dag_id`, `execution_date`, `window_start`, `window_end`, `rows_loaded`, `dbt_models_passed`, `dbt_tests_passed`, `dbt_tests_failed`, `bytes_processed`, `duration_seconds`, `status`, `created_at`
  - `meta.freshness_log`: `run_id`, `pipeline_freshness_timestamp`, `data_freshness_timestamp`, `pipeline_freshness_status`, `data_freshness_status`, `checked_at`
  - `meta.anomaly_results`: `observation_date`, `region`, `metric_name`, `current_value`, `rolling_7d_avg`, `pct_deviation`, `anomaly_flag`, `run_id`, `checked_at`

**Assumption:** Meta tables are created as BigQuery tables directly (not dbt models) since they are written to by Airflow Python tasks, not by dbt transformations. The `schema.yml` documents their structure for consistency.

### 2.2 Pipeline State and Run Metrics Tasks

- [x] Implement `record_run_metrics` task: captures rows loaded, dbt results, bytes processed, duration, status; inserts into `meta.run_metrics`
- [x] Implement `update_pipeline_state` task: updates `meta.pipeline_state` with latest successful window and run_id
- [x] Verify: after a successful DAG run, `meta.pipeline_state` and `meta.run_metrics` contain correct entries

**Acceptance:** Both meta tables populated with accurate run data after each DAG execution.

### 2.3 Freshness Checks

- [x] Configure `dbt source freshness` in `sources.yml`:
  - `loaded_at_field: _ingestion_timestamp`
  - `warn_after: {count: 6, period: hour}`
  - `error_after: {count: 12, period: hour}`
- [x] Wire `dbt_source_freshness` task into DAG (pre-`dbt_build`)
- [x] Implement post-`dbt_build` data freshness check: compute `MAX(observation_timestamp)` from staging, determine fresh/stale status
- [x] Implement freshness log writer: insert both signals into `meta.freshness_log`
- [x] Verify: `meta.freshness_log` contains entries with both pipeline and data freshness timestamps

**Acceptance:** Freshness log populated with two-signal entries after each run.

### 2.4 Anomaly Detection

- [x] Implement `check_anomalies` task:
  - Query mart aggregates for current period
  - Compute rolling 7-day average per region + metric
  - Calculate `pct_deviation`
  - Flag as anomaly if `|pct_deviation| > 50%`
  - Insert results into `meta.anomaly_results`
- [x] Ensure anomaly check is **warning-only** (does not fail DAG)
- [x] Verify: `meta.anomaly_results` populated after runs

**Acceptance:** Anomaly results table populated; DAG succeeds even when anomalies are detected.

---

## Phase 3: Serving Layer (FastAPI + MCP)

> **Goal:** Build the read-only serving layer that exposes pre-computed indicators and pipeline health through REST and MCP interfaces.

### 3.1 Project Scaffold

- [x] Create `serving-fastapi/` directory structure: `app/routers/`, `app/services/`, `app/repositories/`, `app/schemas/`, `app/cache/`, `app/config/`, `app/health/`, `app/exceptions/`
- [x] Create `serving-fastapi/pyproject.toml` declaring dependencies: `fastapi`, `uvicorn`, `pydantic`, `google-cloud-bigquery`, `cachetools`. Local install via `cd serving-fastapi && uv sync`.
- [x] Create `serving-fastapi/app/main.py` — the canonical entrypoint. The `app` object is defined here. Includes router registration and exception handlers.
- [x] Create `serving-fastapi/Dockerfile` (container can install from `pyproject.toml` using pip or uv; container build is an implementation detail)

### 3.2 Config and BigQuery Client

- [x] Implement `app/config/settings.py`: reads `GCP_PROJECT_ID`, `BQ_DATASET_MARTS`, `BQ_DATASET_META`, `PORT` (default `8090`), `GOOGLE_APPLICATION_CREDENTIALS` from environment
- [x] Implement BigQuery client initialization using Application Default Credentials
- [x] Implement base repository with query execution helper

### 3.3 Control Plane Endpoints

- [x] Implement `GET /health` — service-level health check, no BigQuery dependency, returns 200
- [x] Implement `GET /freshness` — reads `meta.freshness_log`, returns latest pipeline + data freshness timestamps, combined `freshness_status` (worse of two signals)
- [x] Implement `GET /pipeline/status` — reads `meta.pipeline_state`, returns latest sync window, run ID
- [x] Implement `GET /anomalies` — reads `meta.anomaly_results`, returns recent anomaly summary
- [x] Define Pydantic response schemas for all control plane endpoints

**Acceptance:** Each endpoint returns valid, schema-conformant responses. Health returns 200 independently of BigQuery.

### 3.4 Metric Endpoints

- [x] Implement load metrics endpoint — accepts region, time range, granularity (hourly/daily); reads `agg_load_hourly` or `agg_load_daily`
- [x] Implement generation mix endpoint — accepts region, time range; reads `agg_generation_mix`
- [x] Implement top regions endpoint — accepts `start_date`, `end_date`, `limit` (top N **per `observation_date`**); reads `agg_top_regions`. Returns pre-computed daily rankings ordered by `observation_date ASC, rank ASC`. No cross-day aggregation.
- [x] Define Pydantic request validation and response schemas for all metric endpoints
- [x] All data responses include metadata: `data_as_of`, `pipeline_run_id`, `freshness_status`

**Acceptance:** Metric endpoints return pre-computed data with correct metadata. No runtime aggregation occurs.

### 3.5 Caching

- [x] Implement in-memory TTL cache using `cachetools` for hot aggregate queries
- [x] Cache key: endpoint + parameters
- [x] TTL configurable (default: 5 minutes)

### 3.6 Error Handling and Logging

- [x] Implement custom exception classes and FastAPI exception handlers
- [x] Implement request-level logging middleware
- [x] Validate parameter inputs; return structured error responses

### 3.7 Serving Layer Verification

- [x] Verify: from `serving-fastapi/`, run `uv run uvicorn app.main:app --host 0.0.0.0 --port 8090` — starts successfully
- [x] Verify: all endpoints return expected responses against populated BigQuery tables
- [x] Verify: Docker build and run works for the serving container

**Acceptance:** All serving API verification criteria from SPEC Section 17 pass.

### 3.8 MCP Server (`stdio`)

- [ ] Create `mcp/` directory structure and `pyproject.toml` for the MCP server package
- [ ] Create a package entrypoint named `voltagehub-mcp` for the MCP server
- [ ] Create MCP `stdio` entrypoint and process bootstrap
- [ ] Wire MCP adapters to shared serving logic and repositories instead of calling REST over HTTP
- [ ] Implement MCP tool registration for the 6 fixed read-only tools:
  - `get_load_trends`
  - `get_generation_mix`
  - `get_top_demand_regions`
  - `check_data_freshness`
  - `get_anomalies`
  - `get_pipeline_status`
- [ ] Implement MCP resource registration for the 4 fixed resources:
  - `schema://grid-metrics`
  - `status://data-quality`
  - `schema://regions`
  - `schema://energy-sources`
- [ ] Ensure `get_top_demand_regions` returns per-day top-N rankings only and does not imply whole-period ranking
- [ ] Ensure `get_generation_mix` percentage support is a row-level derived field for per-day, per-region share only
- [ ] Implement region normalization behavior for canonical `region` and exact case-insensitive `region_name`; do not implement alias matching in v1
- [ ] Keep `schema://regions` v1 limited to `region` and `region_name`
- [ ] Keep `schema://energy-sources` v1 limited to canonical `energy_source`
- [ ] Implement MCP response shaping with `summary`, `highlights`, `data`, and `metadata`
- [ ] Implement MCP-specific validation, overflow, and error behavior, including `unsupported_capability`
- [ ] Add MCP tool/resource tests covering registration, validation, response envelopes, resource payloads, normalization, empty results, and overflow behavior
- [ ] Do not add agent usability tests or remote transport support in this phase
- [ ] Ensure the package can be launched locally with `uv run voltagehub-mcp`
- [ ] Ensure the package can be consumed by agent hosts via `uvx voltagehub-mcp`

**Acceptance:** MCP starts in `stdio` mode, exposes the documented tools/resources, supports `uv run voltagehub-mcp` for local development and `uvx voltagehub-mcp` for host integration, passes MCP tool/resource tests, and defers all detailed MCP contracts to `DOCS/MCP.md`.

---

## Phase 4: CI, Documentation, and Polish

> **Goal:** CI pipelines, project documentation, linting, and operational readiness.

### 4.1 GitHub Actions CI

- [x] Create `.github/workflows/lint.yml`: triggers on push/PR; runs `sqlfluff lint` on dbt SQL + `ruff check` on Python
- [x] Create `.github/workflows/dbt_compile.yml`: triggers on push/PR; runs `dbt deps && dbt parse --target ci --no-populate-cache` for offline dbt project validation
- [x] Create `.github/workflows/terraform_validate.yml`: triggers on push/PR to `terraform/`; runs `terraform fmt -check` + `terraform validate`
- [x] Verify: current Phase 1 / 2 workflows pass on clean PRs; expand CI again when Phase 3 adds serving-layer tests

### 4.2 Documentation

- [x] Create `README.md` with: project overview, prerequisites, setup instructions, deployment steps, usage examples
- [x] Generate dbt documentation: `dbt docs generate`
- [x] Ensure every dbt model and column has a `description` in `schema.yml`

### 4.3 Sample Mode

- [x] Implement `SAMPLE_MODE=true` behavior: extract minimal window, load to separate dataset, `dbt build --target sample`
- [x] Document sample mode usage in README

### 4.4 Linting Configuration

- [x] Configure `sqlfluff` for BigQuery dialect
- [x] Configure `ruff` for Python linting
- [x] Add lint targets to Makefile (local lint commands use `uv run ruff check`, `uv run sqlfluff lint`)

---

## Dependency Graph

```
Phase 1.1 (Terraform) ──► Phase 1.2 (Docker/Airflow)
                               │
                               ▼
                         Phase 1.3 (Extraction)
                               │
                               ▼
                         Phase 1.4 (Airflow DAG)
                               │
                               ▼
                         Phase 1.5 (dbt Staging)
                               │
                               ▼
                         Phase 1.6 (dbt Marts)
                               │
  ┌────────────────────────────┤
  ▼                            ▼
Phase 2 (Meta/Freshness)   Phase 1.7 (Makefile)
  │
  ▼
Phase 3 (Serving Layer)
  │
  ▼
Phase 4 (CI/Docs/Polish)
```

Phase 2 depends on Phase 1 (needs populated mart tables to compute anomalies). Phase 3 depends on Phase 2 (needs meta tables for control plane endpoints). Phase 4 can partially overlap with Phase 3.
