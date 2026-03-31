# ARCHITECTURE.md — VoltageHub

---

## 1. Project Purpose

This project builds a **batch analytics data product** on GCP that incrementally extracts U.S. grid operations data from EIA public APIs, lands raw responses in GCS, transforms them through a layered BigQuery warehouse (raw → staging → marts → meta) using dbt, and exposes fixed analytical indicators and pipeline health through a lightweight serving layer composed of a FastAPI REST API and a stdio MCP server. The pipeline is orchestrated by Apache Airflow, provisioned via Terraform, and containerized with Docker Compose for local development.

---

## 2. System Boundaries

### In Scope

- Time-window-driven batch ingestion of EIA grid data
- Raw landing in GCS with replay and backfill support
- BigQuery warehouse: `raw`, `staging`, `marts`, `meta` datasets
- dbt transformations, tests, freshness checks, anomaly detection
- Airflow DAG for end-to-end orchestration (scheduled sync + backfill)
- Serving layer with a FastAPI REST API and a stdio MCP server
- Terraform IaC for core GCP infrastructure
- Docker Compose local deployment
- GitHub Actions CI (lint, offline dbt parse, validate)

### Out of Scope

- Real-time streaming (Kafka, Flink)
- Distributed compute (Spark, Dataproc)
- gRPC, microservice splitting, Kubernetes
- HTTP, SSE, or other remote MCP transports
- Redis or external caching
- Dynamic SQL / ad-hoc query surface
- ML/forecasting models
- Cloud-managed Airflow (Cloud Composer)
- Enterprise alerting platforms

---

## 3. Major Components

### 3.1 Infrastructure (Terraform)

**Directory:** `terraform/`

Provisions:
- GCS bucket for raw landing zone
- BigQuery datasets: `raw`, `staging`, `marts`, `meta`
- Service account + IAM bindings (`bigquery.dataEditor`, `bigquery.jobUser`, `storage.objectAdmin`)

State: local by default (`.gitignore` excludes `terraform.tfstate*`).

### 3.2 ELT Pipeline (Airflow)

**Directory:** `airflow/`

Single DAG: `eia_grid_batch`

Responsibilities:
- Extract EIA data for a time window (`data_interval_start` → `data_interval_end`)
- Land raw JSON to GCS
- Load raw data into BigQuery via load jobs
- Trigger dbt freshness checks and builds
- Run anomaly detection
- Record run metrics and update pipeline watermark
- Create the four `meta.*` control-plane tables on demand before writing if they do not already exist

Runtime: Docker Compose with custom Airflow image (`apache/airflow:2.9.3-python3.11` + dbt + GCP SDKs).

### 3.3 Warehouse Transformations (dbt)

**Directory:** `dbt/`

Layers:
- `staging/` — canonicalize raw records into `stg_grid_metrics`
- `marts/core/` — fact table (`fct_grid_metrics`) + dimensions (`dim_region`, `dim_energy_source`)
- `marts/aggregates/` — pre-computed summaries (`agg_load_hourly`, `agg_load_daily`, `agg_generation_mix`, `agg_top_regions`)
- `meta/` — schema definitions for pipeline metadata tables

The `meta/` folder documents the control-plane table contracts for dbt docs consistency only. These tables are not materialized by dbt models; Airflow Python tasks create them on demand and then write the records.

Package dependency: `dbt-labs/dbt_utils` (>=1.0.0, <2.0.0)

### 3.4 Serving API (FastAPI REST Adapter)

**Directory:** `serving-fastapi/`
**Entrypoint:** `serving-fastapi/app/main.py` (the `app` object is defined here)
**Dependencies:** declared in `serving-fastapi/pyproject.toml`; managed locally via `uv`

Read-only REST query facade over pre-built aggregate and meta tables.

Packages (under `serving-fastapi/app/`):
- `routers/` — endpoint handlers
- `services/` — business logic, cache interaction
- `repositories/` — BigQuery client, query execution
- `schemas/` — Pydantic v2 request/response models
- `cache/` — optional in-memory TTL cache (`cachetools`)
- `config/` — settings, BigQuery client init
- `health/` — health/status endpoints
- `exceptions/` — error handlers

Data scope: reads **only** from `marts.agg_*` and `meta.*` tables. Never queries `raw`, `staging`, or `fct_grid_metrics`.

### 3.5 MCP Server (`stdio`)

**Directory:** `mcp/`
**Entrypoint:** `mcp/app/main.py`
**Dependencies:** declared in `mcp/pyproject.toml`; managed locally via `uv`

Read-only MCP interface for LLM agents over the same serving-safe warehouse outputs.

Recommended structure (under `mcp/app/`):
- `adapters/` — MCP-to-service translation layer
- `tools/` — fixed MCP tool definitions
- `resources/` — fixed MCP resource definitions
- `config/` — settings and shared client wiring

Dependency direction:

```text
BigQuery repositories -> shared service semantics -> FastAPI REST adapters
BigQuery repositories -> shared service semantics -> MCP stdio adapters
```

Important constraints:
- MCP is `stdio` only
- MCP must not call the REST API over HTTP
- MCP is another serving interface, not a second analytics engine
- REST and MCP share core business semantics, while MCP may add adapter-level agent-facing safety semantics

Data scope:
- REST reads `marts.agg_*` and `meta.*`
- MCP reads `marts.agg_*`, `meta.*`, and may additionally read `marts.dim_region` and `marts.dim_energy_source` for schema resources and normalization support

For detailed MCP tool/resource contracts, normalization rules, truncation rules, and error semantics, defer to `DOCS/MCP.md`.

### 3.6 CI (GitHub Actions)

**Directory:** `.github/workflows/`

Workflows:
- `lint.yml` — `sqlfluff lint` (BigQuery dialect) + `ruff check`
- `dbt_compile.yml` — `dbt deps && dbt parse --target ci --no-populate-cache`
- `terraform_validate.yml` — `terraform fmt -check` + `terraform validate`

CI does not connect to GCP; syntax and quality checks only.

---

## 4. Data Flow

```
EIA Public API
    │
    ▼
extract_grid_batch        ← PythonOperator, requests EIA data for time window
    │
    ▼
land_raw_to_gcs           ← PythonOperator, uploads raw JSON to GCS
    │                        gs://<bucket>/voltage-hub/raw/year=YYYY/month=MM/day=DD/window=<start_iso>/batch.json
    ▼
load_to_bq_raw            ← PythonOperator, BigQuery load job (WRITE_TRUNCATE on batch_date partition)
    │
    ▼
dbt_source_freshness      ← BashOperator, checks _ingestion_timestamp recency
    │
    ▼
dbt_build                 ← BashOperator, runs staging → marts → tests
    │                        Incremental models use insert_overwrite scoped to affected observation_date set
    ▼
check_anomalies           ← PythonOperator, compares current vs. 7-day rolling avg, writes meta.anomaly_results
    │
    ▼
record_run_metrics        ← PythonOperator, writes to meta.run_metrics
    │
    ▼
update_pipeline_state     ← PythonOperator, updates meta.pipeline_state watermark
    │
    ▼
Serving Layer
    ├── FastAPI REST API  ← fixed HTTP endpoints over aggregate/meta tables
    └── MCP Server        ← fixed stdio tools/resources for agent use
```

### Partition Rebuild Logic (per run)

1. Raw load targets `raw.eia_grid_batch` partitioned by `batch_date` (WRITE_TRUNCATE)
2. DAG computes affected `observation_date` set: `SELECT DISTINCT DATE(period) FROM raw.eia_grid_batch WHERE batch_date = <current>`
3. dbt staging/marts: `insert_overwrite` only on affected `observation_date` partitions
4. Dimensions (`dim_region`, `dim_energy_source`): `merge` on natural keys (always full-scope, small tables)
5. Aggregates: full table rebuild (cheap at expected scale)

Idempotency: re-running any window produces identical results. `max_active_runs=1` prevents concurrent partition collisions.

---

## 5. Storage Layout

### GCS Raw Landing

```
gs://<bucket>/voltage-hub/raw/year=YYYY/month=MM/day=DD/window=<start_iso>/batch.json
```

### BigQuery Datasets

| Dataset   | Tables                                                                                   |
|-----------|------------------------------------------------------------------------------------------|
| `raw`     | `eia_grid_batch` (partitioned by `batch_date`)                                           |
| `staging` | `stg_grid_metrics` (partitioned by `observation_date`, clustered by `region`, `metric_name`) |
| `marts`   | `fct_grid_metrics`, `dim_region`, `dim_energy_source`, `agg_load_hourly`, `agg_load_daily`, `agg_generation_mix`, `agg_top_regions` |
| `meta`    | `pipeline_state`, `run_metrics`, `freshness_log`, `anomaly_results`                      |

---

## 6. Configuration Strategy

### Layers

| Layer                | Mechanism                          | Examples                                                  |
|----------------------|------------------------------------|-----------------------------------------------------------|
| Secrets              | `.env` file (git-ignored)          | `GCP_PROJECT_ID`, `EIA_API_KEY`, key path                 |
| Airflow variables    | `AIRFLOW_VAR_` prefix (injection detail) | Airflow reads `.env` values; prefix injects them as Airflow Variables at runtime |
| Airflow connections  | `AIRFLOW_CONN_` prefix             | `AIRFLOW_CONN_GOOGLE_CLOUD_DEFAULT`                       |
| dbt profiles         | `profiles.yml` with `env_var()`    | `{{ env_var('GCP_PROJECT_ID') }}`                         |
| dbt artifacts        | `.env` or env vars                 | `DBT_RUN_RESULTS_PATH=/opt/airflow/dbt/target/run_results.json` |
| Integration tests    | optional env vars                  | `VOLTAGE_HUB_RUN_PIPELINE_TESTS=1`, `VOLTAGE_HUB_RUN_HEAVY_PIPELINE_TESTS=1`, `VOLTAGE_HUB_TEST_EXECUTION_DATE=2026-03-27T01:00:00+00:00` |
| Terraform variables  | `terraform.tfvars` (git-ignored)   | `project_id`, `region`, `bucket_name`                     |
| Serving layer        | `.env` or env vars                 | `GCP_PROJECT_ID`, `BQ_DATASET_MARTS`, `BQ_DATASET_META`, `PORT`, `CACHE_TTL_SECONDS` |
| Sample mode          | `.env` or env vars                 | `SAMPLE_MODE`, `BQ_DATASET_RAW_SAMPLE`, `BQ_DATASET_STAGING_SAMPLE`, `BQ_DATASET_MARTS_SAMPLE`, `BQ_DATASET_META_SAMPLE` |

### Authentication

- GCP service account JSON key mounted at `/opt/airflow/keys/service-account.json`
- `GOOGLE_APPLICATION_CREDENTIALS` set to key path
- No secrets in code or Docker images

---

## 7. Error Handling Strategy

### API Extraction Errors

| Scenario              | Behavior                                                   |
|-----------------------|------------------------------------------------------------|
| 2xx success           | Proceed to GCS landing                                     |
| 429 rate limit        | Retry with exponential backoff (base 60s, max 3 retries)   |
| 5xx server error      | Retry up to 3 times with 2-minute backoff                  |
| Timeout               | Connection 120s, read 300s — retry up to 3                 |
| Empty/malformed       | Validate response structure; fail task if invalid           |

### Airflow-Level

- Task retries: 2, delay 5 minutes
- DAG run timeout: 2 hours
- `max_active_runs=1` prevents concurrent collisions

### dbt Test Failures

- `unique`, `not_null`, `accepted_values`, `relationships` failures **fail** the DAG run

### Freshness

- `error_after` threshold breach **fails** the DAG run
- `warn_after` threshold breach is **warning only**

### Anomaly Detection

- Deviation > 50% from 7-day rolling average is **warning only** — does not fail the DAG

---

## 8. Execution Modes

| Mode           | Description                                                                          |
|----------------|--------------------------------------------------------------------------------------|
| Scheduled      | Incremental sync on configured schedule (hourly default), `catchup=True`             |
| Backfill       | Airflow generates runs for missed intervals; `airflow dags backfill` for manual runs |
| Sample         | `SAMPLE_MODE=true` — minimal single-window validation, separate BigQuery datasets, `dbt build --target sample`  |

---

## 9. Design Decisions and Trade-offs

| Decision                                      | Rationale                                                                               |
|-----------------------------------------------|-----------------------------------------------------------------------------------------|
| `max_active_runs=1`                           | Guarantees partition-level idempotency; limits backfill throughput (acceptable at scale) |
| `insert_overwrite` on date partitions         | Idempotent without row-level dedup; simple recovery model                               |
| Aggregate tables as full rebuilds             | Cheap at expected scale (<1000 rows); avoids incremental complexity                     |
| Serving layer reads only serving-safe outputs | REST reads `agg_*` and `meta.*`; MCP may additionally use `dim_region` and `dim_energy_source` for schema resources and normalization support |
| MCP is a first-class serving interface        | Shared business semantics with REST; different transport and response shaping for agents |
| Raw → GCS first, then BigQuery                | Enables replay, backfill, audit trail; decouples from source API                        |
| In-memory TTL cache (optional)                | No external cache infra; simple first version                                           |
| LocalExecutor                                 | Sufficient for single-project scale; avoids Celery/Kubernetes complexity                |
| Sequential backfill                           | Simplification; parallel backfill requires `WRITE_APPEND` + conflict resolution         |
| Two-signal freshness (pipeline + data)        | Distinguishes "pipeline stopped" from "source is delayed"                               |

---

## 10. Data Plane vs. Control Plane

**Data Plane** — analytical data assets:
- Raw data (GCS + BigQuery `raw`)
- Staging (`stg_grid_metrics`)
- Marts (fact, dimension, aggregate tables)

**Control Plane** — pipeline operations and metadata:
- Pipeline state / watermark (`meta.pipeline_state`)
- Run metrics (`meta.run_metrics`)
- Freshness log (`meta.freshness_log`) — pipeline freshness + data freshness
- Anomaly results (`meta.anomaly_results`)

The control plane is **consumer-facing**: the serving layer reads and exposes freshness, pipeline status, and anomaly summaries through dedicated REST endpoints and MCP tools/resources.
These tables are operational tables owned by Airflow tasks rather than dbt materializations.
