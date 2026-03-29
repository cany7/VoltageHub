# SPEC.md — VoltageHub

---

## 0. Project Summary

### Project Type
**Batch-built analytics data product**, scheduled on a configurable interval (hourly by default, configurable) with support for incremental sync and historical backfill.

### Problem Statement
U.S. grid operations data — including regional demand, generation mix, and load patterns — is continuously updated through EIA public data interfaces. Directly consuming these upstream sources for analytical purposes is unreliable and inconsistent: schemas may shift, data may arrive with irregular latency, and ad-hoc queries against raw API responses do not support reproducible analysis, quality assurance, or controlled downstream consumption.

This project addresses the problem by constructing a **batch-built analytics data product** that:
- Incrementally extracts EIA grid operations data in configurable time windows
- Retains raw batch data in a cloud landing zone for replay and auditability
- Builds a layered warehouse (staging → marts → meta) in BigQuery using dbt
- Enforces data quality, freshness monitoring, and anomaly detection at every layer
- Exposes stable, governed analytical indicators through a lightweight serving API

### Project Goal
Build a reproducible, development-ready analytics data product system that delivers:
- Batch orchestration for incremental grid data extraction
- Cloud infrastructure provisioned via IaC
- Raw data lake landing with replay and backfill support
- Layered analytical warehouse with staging, marts, and meta datasets
- dbt-driven transformations, data quality tests, and documentation
- Lightweight REST API serving layer exposing fixed analytical indicators and pipeline health
- Pipeline metadata, freshness monitoring, and anomaly detection as first-class outputs

### What This Project Delivers
This is an analytics data product, not just a data pipeline. The pipeline is the means of production; the deliverables are:
- **Warehouse models**: stable, tested, documented analytical tables
- **Control plane outputs**: freshness status, pipeline state, run metrics, anomaly results
- **Serving API**: programmatic consumption of fixed indicators and pipeline health

---

## 1. Analytical Questions and Consumption Scenarios

### Core Analytical Questions
The serving API should support the following analytical scenarios:
- How does **regional electricity demand (load)** change over time?
- What is the **generation mix** by energy source / fuel type for a given region or time range?
- Which regions have the **highest total demand** over a given period?
- Are there **anomalous spikes or drops** in load or generation compared to recent baselines?
- What is the **current data freshness** and pipeline health status?

### Consumption Scenarios
- **Regional load trend analysis**: tracking demand changes over time by balancing area
- **Generation structure analysis**: breakdown by energy source / fuel type
- **Regional demand comparison**: comparing load across regions
- **Top demand monitoring**: identifying and tracking the highest-demand regions over time
- **Freshness and pipeline status inquiry**: operational health of the data product
- **Anomaly analysis**: detecting and surfacing unusual patterns in grid metrics

### Primary Deliverables
- Cloud-based raw data landing zone in **GCS**
- Layered warehouse datasets in **BigQuery** (staging, marts, meta)
- **dbt** models, tests, freshness checks, and generated documentation
- **Airflow** DAG implementing end-to-end batch orchestration
- Data quality artifacts: freshness checks, anomaly detection results, pipeline run metrics
- **Serving API** (Python FastAPI) exposing fixed analytical indicators
- Architecture documentation, setup instructions, and reproducibility guide

---

## 2. Data Source

### Source
**EIA Grid Data** — publicly available grid operations data from the U.S. Energy Information Administration (EIA), covering electricity demand, generation, and related operational metrics.

### Source Characteristics
- Data is accessible through EIA public data interfaces and downloadable resources
- Supports extraction by **time window** — the window granularity is configurable (hourly by default)
- Contains key dimensions:
  - **Region / Balancing Area**: geographic and operational grid areas
  - **Energy Source / Fuel Type**: generation by source category (natural gas, wind, solar, nuclear, etc.)
  - **Time**: observation timestamps at various granularities
- Suitable for building analytical indicators at multiple time granularities
- Raw responses can be landed as-is before warehouse transformation

### Why This Source Fits
- Continuously updated, making it ideal for incremental batch ingestion
- Rich in dimensional structure (region, fuel type, time) for analytical modeling
- Publicly available and well-documented, supporting reproducibility
- Volume is manageable for a single-project warehouse without requiring distributed processing
- Naturally supports the core analytical scenarios (load trends, generation mix, regional comparison)

### Scope Control
- **Default backfill**: most recent 7 days (sufficient for validation and quality checks)
- **Extended backfill**: configurable up to 90 days for deeper trend analysis
- **Incremental sync**: scheduled extraction of the latest available time window
- Extraction parameters (time range, regions, metrics) are configurable via Airflow variables

---

## 3. Architecture

### Pipeline Type
**Batch** pipeline. Grid operations analytics is a periodic analysis workload, not a real-time control or streaming system.

### Architecture Overview

```
EIA Source (public data interfaces)
    │
    ▼
Extract Batch (time-window-driven)
    │
    ▼
Raw Landing (GCS)
    │
    ▼
BigQuery Raw (source batch records)
    │
    ▼
dbt Staging (canonical metrics)
    │
    ▼
dbt Marts / Aggregates / Meta
    │
    ▼
Consumers
   └── Serving API (Python FastAPI)
```

### Data Plane vs. Control Plane

**Data Plane** — the analytical data assets:
- Raw data (GCS landing zone + BigQuery raw table)
- Staging tables (canonicalized, standardized grid metrics)
- Marts (fact and dimension tables)
- Aggregates (summaries at configurable time granularities)

**Control Plane** — pipeline operations and metadata:
- Pipeline state / watermark (latest successful sync window)
- Run metrics (rows processed, duration, bytes scanned, status)
- Freshness status (latest data timestamp, latency)
- Anomaly check results (deviation flags on key metrics)

The control plane is not just internal bookkeeping — it is consumed by the **serving layer** and exposed to downstream clients.

### System Boundaries

**ELT Layer** is responsible for:
- Source extraction from EIA data interfaces
- Raw batch landing in GCS
- Warehouse modeling (raw → staging → marts → aggregates)
- Freshness, quality, and anomaly checks
- Pipeline state, run metrics, and meta tables

**Serving Layer** is responsible for:
- Fixed-template analytical indicator endpoints (not an ad-hoc query surface)
- Parameter validation and response contract enforcement
- Optional in-memory caching for hot queries
- Health, freshness, and pipeline status exposure
- Request logging

---

## 4. Technology Stack

### Core Stack

| Component | Technology | Version / Detail |
|---|---|---|
| Cloud platform | GCP | — |
| Workflow orchestration | Apache Airflow | 2.9.x (via Docker Compose) |
| Raw storage / landing zone | GCS | — |
| Analytical warehouse | BigQuery | — |
| Transformations | dbt Core | 1.8.x (installed in Airflow container) |
| Infrastructure as code | Terraform | >= 1.5 |
| CI | GitHub Actions | — |
| Containerization | Docker Compose | v2 |

### Serving Layer (Python FastAPI)

| Component | Technology | Version / Detail |
|---|---|---|
| Language | Python | 3.11+ |
| Framework | FastAPI | latest |
| Validation | Pydantic | v2 |
| BigQuery access | BigQuery Python client | — |
| Caching (optional) | `cachetools` or manual TTL dict | in-memory, TTL-based |
| Health / observability | Custom endpoints | — |

### Explicitly Excluded
- Streaming or real-time data processing
- Distributed compute frameworks
- Ad-hoc or arbitrary query serving
- Multi-service / Kubernetes-style deployment
- External caching or serving-store infrastructure in the first version

---

## 5. Deployment and Configuration

### 5.1 Local Development with Docker Compose

All services run in containers for local development.

**Container architecture:**
- **Airflow webserver** — UI on `localhost:8080`
- **Airflow scheduler** — runs DAGs
- **PostgreSQL** — Airflow metadata database

**Key tools installed in the Airflow container image:**
- `dbt-core` + `dbt-bigquery`
- `google-cloud-bigquery`, `google-cloud-storage` (Python SDKs)
- `requests` (for EIA API calls)

**Recommended Airflow executor:** `LocalExecutor`

A custom `Dockerfile` extends the official `apache/airflow:2.9.3-python3.11` image to install:
```
dbt-core==1.8.*
dbt-bigquery==1.8.*
google-cloud-bigquery
google-cloud-storage
requests
```

`dbt deps` must run before any dbt command, either as part of the Docker entrypoint or via `make dbt-deps` after `docker compose up`.

**Docker Compose services:**

| Service | Image | Purpose |
|---|---|---|
| `airflow-webserver` | Custom (extends `apache/airflow:2.9.3`) | Airflow UI |
| `airflow-scheduler` | Custom (same image) | DAG scheduling and execution |
| `postgres` | `postgres:16` | Airflow metadata DB |

Volumes mount local `./airflow/dags`, `./airflow/plugins`, and `./dbt` into the Airflow containers.

### 5.2 Configuration Management

**Principles:**
- No secrets or credentials in code or Docker images
- All environment-specific values are externalized
- A single `.env.example` documents every required variable

**Configuration layers:**

| Layer | Mechanism | Examples |
|---|---|---|
| Secrets | `.env` file (git-ignored) + Docker Compose `env_file` | `GCP_PROJECT_ID`, `GCP_SERVICE_ACCOUNT_KEY_PATH` |
| Airflow variables | `AIRFLOW_VAR_` prefix or JSON seed file | `AIRFLOW_VAR_GCS_BUCKET`, `AIRFLOW_VAR_BQ_DATASET_STAGING` |
| Airflow connections | `AIRFLOW_CONN_` prefix | `AIRFLOW_CONN_GOOGLE_CLOUD_DEFAULT` |
| dbt profiles | `profiles.yml` with `env_var()` | `{{ env_var('GCP_PROJECT_ID') }}` |
| Terraform variables | `terraform.tfvars` (git-ignored) + `variables.tf` | `project_id`, `region`, `bucket_name` |

**Required environment variables (`.env.example`):**

```env
# GCP
GCP_PROJECT_ID=your-gcp-project-id
GCP_REGION=us-central1
GCP_SERVICE_ACCOUNT_KEY_PATH=/opt/airflow/keys/service-account.json

# GCS
GCS_BUCKET_NAME=voltage-hub-raw

# BigQuery
BQ_DATASET_RAW=raw
BQ_DATASET_STAGING=staging
BQ_DATASET_MARTS=marts
BQ_DATASET_META=meta

# Airflow
AIRFLOW__CORE__EXECUTOR=LocalExecutor
AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=postgresql+psycopg2://airflow:airflow@postgres:5432/airflow
AIRFLOW__CORE__LOAD_EXAMPLES=False

# Pipeline
BACKFILL_DAYS=7

# EIA
EIA_API_KEY=your-eia-api-key
```

**GCP authentication:** Mount service account JSON key at `/opt/airflow/keys/service-account.json`. Set `GOOGLE_APPLICATION_CREDENTIALS` to that path.

**Terraform state:** Local state for single-user development. `.gitignore` must exclude `terraform.tfstate*`. Remote GCS backend is optional for multi-user setups.

---

## 6. Scope and Non-Goals

### In Scope
- Time-window-driven batch ingestion of EIA grid data
- Raw landing in GCS with replay/backfill support
- BigQuery raw, staging, marts, and meta datasets
- dbt transformations, tests, freshness, and anomaly checks
- Airflow end-to-end DAG with scheduled sync and backfill
- Lightweight serving API (Python FastAPI)
- IaC for core infrastructure
- Docker Compose local deployment
- CI for linting, offline dbt project validation, and infrastructure validation
- Reproducibility documentation

### Out of Scope
- Real-time streaming (Kafka, Flink)
- Distributed processing (Spark, Dataproc)
- gRPC or multi-service RPC
- Microservice splitting or service mesh
- Kubernetes
- Redis or external caching
- Dynamic SQL / arbitrary query engine
- Ad-hoc analytics query surface
- Complex ML or forecasting
- Real-time operational grid control systems
- Cloud-managed Airflow (Cloud Composer)
- Full enterprise observability or alerting platforms

---

## 7. Repository Structure

```
voltage-hub/
├── terraform/                          # IaC: GCS, BigQuery, IAM, service accounts
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   └── terraform.tfvars.example
├── docker/
│   └── Dockerfile                      # Custom Airflow image with dbt, GCP SDKs
├── airflow/
│   ├── dags/
│   │   └── eia_grid_batch.py           # Main ELT DAG
│   ├── schemas/
│   │   └── raw_eia_batch.json          # Explicit BQ schema for raw landing table
│   └── plugins/                        # Custom operators or helpers
├── dbt/
│   ├── dbt_project.yml
│   ├── packages.yml
│   ├── profiles.yml
│   ├── models/
│   │   ├── staging/
│   │   │   ├── stg_grid_metrics.sql
│   │   │   └── schema.yml
│   │   ├── marts/
│   │   │   ├── core/
│   │   │   │   ├── fct_grid_metrics.sql
│   │   │   │   ├── dim_region.sql
│   │   │   │   ├── dim_energy_source.sql
│   │   │   │   └── schema.yml
│   │   │   └── aggregates/
│   │   │       ├── agg_load_hourly.sql
│   │   │       ├── agg_load_daily.sql
│   │   │       ├── agg_generation_mix.sql
│   │   │       ├── agg_top_regions.sql
│   │   │       └── schema.yml
│   │   └── meta/
│   │       └── schema.yml
│   └── macros/
├── serving-fastapi/                    # FastAPI Serving Layer
│   ├── app/
│   │   ├── routers/
│   │   ├── services/
│   │   ├── repositories/
│   │   ├── schemas/
│   │   ├── cache/
│   │   ├── config/
│   │   ├── health/
│   │   ├── exceptions/
│   │   └── main.py                     # Canonical entrypoint; defines `app` object
│   ├── pyproject.toml
│   └── Dockerfile
├── docs/
├── scripts/                            # Utilities for validation, debugging
├── .github/workflows/                  # CI: lint, dbt parse, terraform validate
├── docker-compose.yml
├── Makefile
├── .env.example
├── .gitignore
└── README.md

### Makefile Targets

| Target | Command | Description |
|---|---|---|
| `make up` | `docker compose up -d` | Start all services |
| `make down` | `docker compose down` | Stop all services |
| `make build` | `docker compose build` | Build custom Airflow image |
| `make backfill` | Trigger DAG via Airflow CLI with catchup | Run initial backfill |
| `make dbt-build` | `dbt build` inside container | Run dbt build |
| `make dbt-docs` | `dbt docs generate` inside container | Generate dbt docs |
| `make dbt-deps` | `dbt deps` inside container | Install dbt packages |
| `make lint` | `sqlfluff lint` + `ruff check` | Lint SQL and Python |
| `make terraform-init` | `terraform init` | Initialize Terraform |
| `make terraform-apply` | `terraform apply` | Provision GCP resources |
| `make terraform-destroy` | `terraform destroy` | Tear down GCP resources |
| `make clean` | Remove local artifacts, logs, temp | Clean up |

---

## 8. Data Flow and Execution Design

### Time-Window-Driven Extraction
Each batch run processes a **defined time window**. The extract step requests EIA grid data for a specific time range, receives the response, and lands it in the raw layer before any warehouse processing.

There is no fixed "one file per hour" assumption. Each run is parameterized by a time window derived from Airflow's scheduling context. The scheduling interval is configurable (hourly by default).

### End-to-End Flow

```
extract_grid_batch              [request EIA data for time window]
    │
    ▼
land_raw_to_gcs                 [persist raw response to GCS]
    │
    ▼
load_to_bq_raw                  [load raw batch into BigQuery raw table]
    │
    ▼
dbt_source_freshness            [verify data freshness pre-check]
    │
    ▼
dbt_build                       [staging canonicalization + marts + tests]
    │
    ▼
check_anomalies                 [anomaly detection on key metrics]
    │
    ▼
record_run_metrics              [capture run stats to meta]
    │
    ▼
update_pipeline_state           [update watermark / sync state]
```

### Raw Landing Requirement
Raw EIA response data **must first land in GCS** before loading into BigQuery. This provides:
- Replay and reprocessing capability
- Backfill support without re-hitting the source API
- Decoupling of serving layer from source API availability
- Audit trail of ingested data

### API Error Handling

| Scenario | Behavior |
|---|---|
| Success (2xx) | Proceed with landing to GCS |
| Rate limit (429) | Retry with exponential backoff (base 60s, max 3 retries) |
| Server error (5xx) | Retry up to 3 times with 2-minute backoff |
| Timeout | Connection 120s, read 300s — retry up to 3 |
| Empty / malformed response | Validate response structure; fail task if invalid |

Task-level retries handle transient failures. Airflow-level retries (2 retries, 5-minute delay) serve as a second safety net.

### Load Method: BigQuery Load Jobs
Raw data is loaded from GCS into BigQuery using **load jobs** (`bigquery.Client.load_table_from_uri`).

- Load jobs are **free** (no per-byte cost)
- Uses `WRITE_TRUNCATE` at the partition level for idempotent reloads
- Uses explicit schema definition checked into `airflow/schemas/`

### Execution Modes
- **Scheduled mode**: incremental sync on configured schedule (hourly by default) via Airflow `catchup=True`
- **Backfill mode**: Airflow generates runs for missed intervals; manual backfill via `airflow dags backfill`
- **Sample mode**: `SAMPLE_MODE=true` — extracts a minimal time window, loads to separate dataset, runs `dbt build --target sample` for local validation

---

## 9. Incremental Loading Strategy

### Incremental Grain
Each DAG run processes **one time window** as determined by Airflow's scheduling interval. The scheduling interval is hourly by default but configurable.

### Interval Source: Airflow `data_interval_start`
With `catchup=True` and a configured schedule, Airflow generates one DAG run per interval. Each run receives `data_interval_start` and `data_interval_end` as template variables. The extraction time window is derived directly from these values.

### Watermark / Pipeline State (Recovery)
BigQuery table: `meta.pipeline_state`

Fields:
- `pipeline_name` (STRING)
- `last_successful_window_start` (TIMESTAMP) — start of the latest successfully processed window
- `last_successful_window_end` (TIMESTAMP)
- `last_successful_run_id` (STRING) — Airflow `run_id` of the latest successful run; used by the serving layer to populate `pipeline_run_id` in response metadata
- `updated_at` (TIMESTAMP)

The watermark is updated at the end of each successful run. It is **not read during normal execution** — it exists solely for disaster recovery if Airflow metadata is lost.

### Incremental Logic (Per Run)
1. Derive time window from `{{ data_interval_start }}` / `{{ data_interval_end }}`
2. Extract EIA data for that time window
3. Land raw response to GCS: `gs://<bucket>/voltage-hub/raw/year=YYYY/month=MM/day=DD/window=<start>/batch.json`
4. Load into BigQuery raw table partition with `WRITE_TRUNCATE`
5. **Determine affected `observation_date` set**: after raw load, compute `SELECT DISTINCT DATE(period) FROM raw.eia_grid_batch WHERE batch_date = <current_batch_date>`. This set of dates is the **rebuild scope** for downstream layers.
6. Run `dbt build` — staging and mart `insert_overwrite` only touches the partitions corresponding to the affected `observation_date` set
7. Record run metrics
8. Update pipeline state watermark

### Partition Rebuild Rules
The project uses explicit, deterministic partition targeting at every layer. Each DAG run does **not** rebuild all partitions — it only overwrites the specific `observation_date` partitions affected by the current batch.

**Step-by-step:**

1. **Raw load**: Load job targets `raw.eia_grid_batch`, partitioned by `batch_date`. Uses `WRITE_TRUNCATE` on the target `batch_date` partition. Re-running a window overwrites the same partition with identical data.
2. **Affected date set**: After raw load, the DAG computes the distinct `observation_date` values present in the newly loaded batch. This set (typically 1–2 dates, since a single extraction window may span a date boundary) defines the rebuild scope for all downstream layers.
3. **dbt staging**: `stg_grid_metrics` uses `incremental` with `insert_overwrite` on `observation_date`. dbt rebuilds **only** the partitions in the affected date set. The `is_incremental()` filter restricts the source scan to the affected dates.
4. **dbt marts**: `fct_grid_metrics` uses `insert_overwrite` on `observation_date`, scoped to the same affected date set. Dimension tables (`dim_region`, `dim_energy_source`) use `merge` on their natural keys — these are always full-scope since dimensions are small.
5. **Aggregates**: Full table rebuilds (cheap at expected scale, typically < 1000 rows per table).

**Idempotency guarantee:**
- Re-running any window re-loads the same raw partition, recomputes the same affected date set, and overwrites exactly the same downstream partitions — producing identical results.
- `max_active_runs=1` prevents concurrent runs from colliding on overlapping partitions.
- Backfill runs sequentially, which is acceptable at this project's scale.

> **Trade-off:** Sequential `max_active_runs=1` limits backfill throughput. This is an intentional simplification. If parallel backfill is needed later, the strategy can be migrated to `WRITE_APPEND` with dbt-level conflict resolution, but that is not the default path.

### Raw Path Convention
```
gs://<bucket>/voltage-hub/raw/year=YYYY/month=MM/day=DD/window=<start_iso>/batch.json
```

---

## 10. BigQuery Warehouse Design

### 10.1 Datasets

| Dataset | Purpose |
|---|---|
| `raw` | Source batch landing — minimally processed records from EIA |
| `staging` | dbt staging models — canonicalized, standardized |
| `marts` | Fact, dimension, and aggregate tables for analytical consumption |
| `meta` | Pipeline state, run metrics, freshness results, anomaly checks |

### 10.2 Raw Layer

#### `raw.eia_grid_batch`

This is the **source batch landing table**. Its schema closely mirrors the structure of the EIA API response or downloaded resource, with minimal transformation. The purpose is to preserve a replayable copy of what was received from the source.

**Design principles:**
- Schema reflects the source response structure, not the canonical analytical model
- Retains all source fields without normalization or metric-name pivoting
- Supports replay and reprocessing: any batch can be re-loaded from GCS
- Downstream consumers (dbt staging) never depend on the source API directly

**Schema (explicit — checked into `airflow/schemas/raw_eia_batch.json`):**

| Column | BigQuery Type | Notes |
|---|---|---|
| `respondent` | STRING | Source-level entity / balancing authority identifier |
| `respondent_name` | STRING | Human-readable name from source |
| `type` | STRING | Response category (e.g., demand, generation, interchange) |
| `type_name` | STRING | Human-readable type label from source |
| `value` | FLOAT64 | Reported value |
| `value_units` | STRING | Unit of measurement as reported by source |
| `period` | STRING | Observation period as reported (ISO timestamp or date string) |
| `fueltype` | STRING (NULLABLE) | Fuel/source type code (for generation data) |
| `fueltype_name` | STRING (NULLABLE) | Human-readable fuel type label |
| `batch_date` | DATE | Date of the extraction batch, used for partitioning |
| `_batch_id` | STRING | Identifies the extraction batch |
| `_source_url` | STRING | Source endpoint or resource URL for traceability |
| `_ingestion_timestamp` | TIMESTAMP | Pipeline-generated, used for freshness checks |

**Partitioning:** `batch_date`
**Clustering:** none at raw layer

> **Note:** The raw schema above represents the expected landing shape for the currently selected EIA data interface family. If a different EIA endpoint or resource is adopted in the future, only the raw schema and the staging-layer mapping logic need to change. The `stg_grid_metrics` canonical model is the stable downstream contract — marts, aggregates, and the serving API all depend on the staging layer, never on raw directly. The key invariant is: raw reflects source shape, not canonical shape.

### 10.3 Staging Layer

#### `staging.stg_grid_metrics` (dbt model)

This is the **canonical metrics table** — the single source of truth for downstream marts. The dbt staging model transforms raw source records into a standardized, long-format grid metrics table.

**Responsibilities:**
- Parse and cast source fields into consistent types
- Normalize region identifiers and energy source codes
- Convert `period` strings to proper TIMESTAMP
- Apply surrogate key for grain-level uniqueness
- Partition-level idempotent rebuild via `insert_overwrite` (no row-level dedup needed under `max_active_runs=1`)

Core fields:
- `metric_surrogate_key` — `dbt_utils.generate_surrogate_key(['region', 'observation_timestamp', 'metric_name', 'energy_source'])`
- `region` — standardized region / balancing area code (from `respondent`)
- `region_name` — human-readable region name (from `respondent_name`)
- `observation_timestamp` — parsed TIMESTAMP (from `period`)
- `observation_date` — DATE, derived from `observation_timestamp`
- `metric_name` — standardized metric type (from `type` / `type_name`)
- `metric_value` — FLOAT64 (from `value`)
- `energy_source` (nullable) — standardized fuel type (from `fueltype`); allowed Voltage Hub codes: `BAT`, `BIO`, `COL`, `GEO`, `HPS`, `HYC`, `NG`, `NUC`, `OES`, `OIL`, `OTH`, `PS`, `SNB`, `SUN`, `UES`, `UNK`, `WAT`, `WNB`, `WND`
- `unit` — standardized unit (from `value_units`)
- `_ingestion_timestamp` — passed through from raw

**Partitioning:** `observation_date`
**Clustering:** `region`, `metric_name`

### 10.4 Marts Layer

#### Core Models

- **`marts.fct_grid_metrics`** — one row per observation (region × timestamp × metric × source). Partitioned by `observation_date`, clustered by `region`, `metric_name`.
- **`marts.dim_region`** — unique regions / balancing areas with `region` (PK), `region_name`.
- **`marts.dim_energy_source`** — unique energy sources / fuel types with `energy_source` (PK), optional category grouping.

#### Aggregate Models

Aggregates are consumption-layer summaries built from mart-level data. They are not tied to source granularity.

- **`marts.agg_load_hourly`** — hourly load/demand metrics by region
- **`marts.agg_load_daily`** — daily load summaries by region (avg, min, max, total)
- **`marts.agg_generation_mix`** — generation breakdown by energy source. Default grain: **region × observation_date × energy_source**. This is the standard consumption granularity for the serving API. Broader time-window aggregations (weekly, monthly) are left to the API query layer or upstream consumer.
- **`marts.agg_top_regions`** — daily ranked regions by demand. Default grain: **observation_date × region**, ranked by daily total load. Each row contains:
  - `observation_date` (DATE)
  - `region` (STRING)
  - `region_name` (STRING)
  - `daily_total_load` (FLOAT64) — sum of load for the region on that date
  - `rank` (INT64) — rank within the `observation_date` (1 = highest load)

  The serving API consumes this table directly for "top N per day" queries over a date range. The `limit` parameter in the API applies per `observation_date`, not across the entire range.

These aggregates are the primary data sources for the serving API.

### 10.5 Meta Layer

| Table | Purpose | Consumed by |
|---|---|---|
| `meta.pipeline_state` | Latest successful sync window, watermark, last run ID | `/pipeline/status` endpoint |
| `meta.run_metrics` | Per-run statistics: rows, bytes, duration, status | Internal observability (not directly exposed via API) |
| `meta.freshness_log` | Pipeline freshness and data freshness per run (see Section 12.2) | `/freshness` endpoint |
| `meta.anomaly_results` | Anomaly detection outputs on key grid metrics | `/anomalies` endpoint |

The meta layer is a **first-class consumer-facing dataset**: the serving API reads freshness, pipeline status, and anomaly summaries from these tables and exposes them through dedicated endpoints.
The meta tables are operational control-plane tables owned by Airflow tasks. If one does not exist yet, the Airflow Python task that writes to it creates it on demand before inserting or updating records. They are documented in dbt for schema consistency, but they are not materialized by dbt models.

### 10.6 Partitioning and Clustering Rationale
- Tables partitioned by date because queries overwhelmingly filter by time range
- Clustered by `region` and `metric_name` because downstream queries group/filter by these dimensions
- Aggregate tables further reduce query cost and latency for API consumers

---

## 11. Transformations with dbt

### dbt Package Dependencies

```yaml
packages:
  - package: dbt-labs/dbt_utils
    version: [">=1.0.0", "<2.0.0"]
```

### dbt Layers
- **`staging/`** — Canonicalization: type casting, field normalization, surrogate key generation. Transforms raw source records into the canonical `stg_grid_metrics` table via partition-level idempotent rebuild.
- **`marts/core/`** — Fact and dimension models
- **`marts/aggregates/`** — Consumption-layer summaries at various time granularities
- **`meta/`** — Pipeline metadata schema definitions

### dbt Model Materializations

| Model | Materialization | Strategy | Key |
|---|---|---|---|
| `stg_grid_metrics` | `incremental` | `insert_overwrite` | `partition_by: {field: observation_date, data_type: date}` |
| `fct_grid_metrics` | `incremental` | `insert_overwrite` | `partition_by: {field: observation_date, data_type: date}` |
| `dim_region` | `incremental` | `merge` | `unique_key: region` |
| `dim_energy_source` | `incremental` | `merge` | `unique_key: energy_source` |
| `agg_load_hourly` | `table` | full rebuild | — |
| `agg_load_daily` | `table` | full rebuild | — |
| `agg_generation_mix` | `table` | full rebuild | — |
| `agg_top_regions` | `table` | full rebuild | — |

All incremental models use `insert_overwrite`, scoped to the affected `observation_date` set determined during each DAG run (see Section 9 Partition Rebuild Rules). This ensures each run only touches the partitions it needs to.

### dbt Requirements
- `sources.yml` defining `raw.eia_grid_batch` as the source
- `schema.yml` with descriptions and tests for every model
- Docs generation with `dbt docs generate`

---

## 12. Data Quality Requirements

### 12.1 dbt Tests (run as part of `dbt build`)
At minimum:
- `not_null` on `metric_surrogate_key`, `observation_timestamp`, `region`, `metric_name`
- `unique` on `metric_surrogate_key`
- `not_null` on `metric_value`
- `accepted_values` on `metric_name` (expected metric types)
- `accepted_values` on `energy_source` using the documented Voltage Hub fuel-code set (`BAT`, `BIO`, `COL`, `GEO`, `HPS`, `HYC`, `NG`, `NUC`, `OES`, `OIL`, `OTH`, `PS`, `SNB`, `SUN`, `UES`, `UNK`, `WAT`, `WNB`, `WND`)
- `relationships` between `fct_grid_metrics.region` and `dim_region.region`
- `relationships` between `fct_grid_metrics.energy_source` and `dim_energy_source.energy_source`
- Uniqueness at expected grain: `(region, observation_timestamp, metric_name, energy_source)`

### 12.2 Freshness Checks

Freshness is tracked as **two distinct signals**, not a single status:

#### Pipeline Freshness
Measures how recently the pipeline successfully ingested data. Based on `MAX(_ingestion_timestamp)` from the raw table.

- Implemented via `dbt source freshness` as a pre-step before `dbt build`
- Detects stale pipelines (e.g., DAG not running, extract failures)
- If `_ingestion_timestamp` exceeds the `error_after` threshold, the run fails

```yaml
sources:
  - name: raw
    tables:
      - name: eia_grid_batch
        loaded_at_field: _ingestion_timestamp
        freshness:
          warn_after:
            count: 6
            period: hour
          error_after:
            count: 12
            period: hour
```

Thresholds are configurable and should be tuned to the actual scheduling interval.

#### Data Freshness
Measures how recent the actual observation data is. Based on `MAX(observation_timestamp)` from `staging.stg_grid_metrics` (or equivalently from `marts.fct_grid_metrics`).

- Computed after `dbt build` as a post-build check
- Detects source-side delays: the pipeline may be running on schedule, but EIA may not have published recent data yet
- Recorded as a separate field in `meta.freshness_log`
- The default consumer-facing stale threshold is 6 hours: `data_freshness_status` is `fresh` when `checked_at - data_freshness_timestamp <= 6 hours`, otherwise `stale`

#### `meta.freshness_log` Schema

| Column | Type | Notes |
|---|---|---|
| `run_id` | STRING | Airflow `run_id` |
| `pipeline_freshness_timestamp` | TIMESTAMP | `MAX(_ingestion_timestamp)` from raw table at check time |
| `data_freshness_timestamp` | TIMESTAMP | `MAX(observation_timestamp)` from staging/marts at check time |
| `pipeline_freshness_status` | STRING | `fresh` \| `stale` — based on `_ingestion_timestamp` vs. threshold |
| `data_freshness_status` | STRING | `fresh` \| `stale` — based on `observation_timestamp` vs. a 6-hour expected recency threshold |
| `checked_at` | TIMESTAMP | When the check was performed |

The serving API's `/freshness` endpoint returns **both** signals. The `freshness_status` field in the response contract is derived from the **worse** of the two (if either is `stale`, the combined status is `stale`).

### 12.3 Anomaly Checks

**Target table:** `meta.anomaly_results`

Fields:
- `observation_date` (DATE)
- `region` (STRING)
- `metric_name` (STRING)
- `current_value` (FLOAT64)
- `rolling_7d_avg` (FLOAT64)
- `pct_deviation` (FLOAT64)
- `anomaly_flag` (BOOLEAN)
- `run_id` (STRING)
- `checked_at` (TIMESTAMP)

**Logic:**
- After `dbt build`, query mart-level aggregates for the current period
- Compare against the rolling 7-day average for the same region and metric
- The rolling baseline uses the prior 7 calendar days, excluding the current `observation_date`
- If fewer than 1 prior day is available or the rolling average is `0`, store `pct_deviation = NULL` and `anomaly_flag = FALSE`
- Flag as anomaly if `|pct_deviation| > 50%`
- Insert results into `meta.anomaly_results`

**Failure policy:** Anomaly detection is **warning-only** — it does not fail the DAG.

### Failure Policy Summary

| Check Type | Trigger | DAG Behavior |
|---|---|---|
| dbt test failure | `unique`, `not_null`, `accepted_values`, `relationships` | **Fail** DAG run |
| Source freshness `error_after` | Source data beyond error threshold | **Fail** DAG run |
| Source freshness `warn_after` | Source data beyond warn threshold | **Warning** only |
| Anomaly check | Deviation > 50% from 7-day avg | **Warning** only |

---

## 13. Airflow DAG Design

### Main DAG
`eia_grid_batch`

### DAG Configuration
- **Schedule:** `@hourly` (configurable — this is the default, not a structural constraint)
- **Start date:** configurable (defaults to 7 days ago for initial backfill)
- **Catchup:** `True`
- **Max active runs:** `1` (ensures partition-level idempotency without collision)
- **Default retries:** `2`
- **Retry delay:** `timedelta(minutes=5)`
- **Dagrun timeout:** `timedelta(hours=2)`

### Task Sequence

```
extract_grid_batch              [request EIA data for time window]
    │
    ▼
land_raw_to_gcs                 [persist raw data to GCS]
    │
    ▼
load_to_bq_raw                  [BigQuery load job → raw.eia_grid_batch]
    │
    ▼
dbt_source_freshness            [dbt source freshness check]
    │
    ▼
dbt_build                       [staging + marts + tests]
    │
    ▼
check_anomalies                 [anomaly detection → meta.anomaly_results]
    │
    ▼
record_run_metrics              [insert run stats → meta.run_metrics]
    │
    ▼
update_pipeline_state           [update meta.pipeline_state watermark]
```

### Task Implementation Details

| Task | Operator | Timeout | Notes |
|---|---|---|---|
| `extract_grid_batch` | `PythonOperator` | 10 min | Request EIA data for `{{ data_interval_start }}` to `{{ data_interval_end }}` |
| `land_raw_to_gcs` | `PythonOperator` | 10 min | Upload raw response to GCS landing zone |
| `load_to_bq_raw` | `PythonOperator` | 15 min | `bigquery.Client.load_table_from_uri()` with `WRITE_TRUNCATE` on partition |
| `dbt_source_freshness` | `BashOperator` | 5 min | `dbt source freshness` |
| `dbt_build` | `BashOperator` | 30 min | `dbt build` |
| `check_anomalies` | `PythonOperator` | 5 min | Anomaly detection SQL → `meta.anomaly_results` |
| `record_run_metrics` | `PythonOperator` | 5 min | Insert run statistics → `meta.run_metrics` |
| `update_pipeline_state` | `PythonOperator` | 5 min | Update watermark in `meta.pipeline_state` |

### Design Requirements
- DAG is end-to-end — no critical steps remain manual
- Each run processes one time window derived from Airflow's `data_interval_start` / `data_interval_end`
- Backfill via Airflow's native catchup — no custom interval computation
- All tasks authenticate via mounted service account credentials

---

## 14. Serving Layer Design

### Functional Scope
The serving layer exposes a **set of fixed-template analytical endpoints**. The serving layer is a **thin, read-only query façade** with predefined query templates — it is explicitly **not** a general-purpose analytics query surface.

**Data scope constraint:** The serving layer reads **only** from pre-built aggregate tables (`marts.agg_*`) and meta tables (`meta.*`). It does **not** query large fact tables (`fct_grid_metrics`) or perform runtime aggregation. All heavy computation is done by dbt at build time; the serving layer simply retrieves and filters pre-computed results.

**Metric endpoints (fixed query templates):**
- Load metrics by region and time granularity → reads `marts.agg_load_hourly` / `marts.agg_load_daily`
- Generation mix by energy source for a given region / time range → reads `marts.agg_generation_mix`
- Top regions by total demand → reads marts.agg_top_regions

**Control plane endpoints:**
- `/health` — service health check (service-level, no BigQuery dependency)
- `/freshness` — pipeline freshness + data freshness → reads `meta.freshness_log`
- `/pipeline/status` — latest successful sync window, pipeline state → reads `meta.pipeline_state`
- `/anomalies` — recent anomaly summary → reads `meta.anomaly_results`

> **Note:** `meta.run_metrics` contains internal pipeline telemetry (rows loaded, bytes processed, duration). It is available for operational debugging but is not exposed as a public API endpoint.

### Response Contract
Every data endpoint response includes metadata fields:
- `data_as_of` — latest `data_freshness_timestamp` (from `meta.freshness_log`)
- `pipeline_run_id` — identifier of the latest successful pipeline run (from `meta.pipeline_state.last_successful_run_id`)
- `freshness_status` — combined status: `fresh` | `stale` | `unknown` (derived from the worse of `pipeline_freshness_status` and `data_freshness_status` in `meta.freshness_log`)

### Constraints
- **Fixed-template endpoints only** — each endpoint maps to a predefined query against specific `agg_*` or `meta.*` tables
- **No fact table queries** — the serving layer never reads `fct_grid_metrics` directly; all metrics are served from pre-aggregated tables
- **No runtime re-aggregation** — no `GROUP BY`, `SUM()`, or window functions at query time; the serving layer returns pre-built rows with simple `WHERE` filters
- **No ad-hoc query surface** — no free-form metric selection, no arbitrary grouping, no dynamic SQL exposure
- **No user-defined filters beyond predefined parameters** (region, time range, granularity)
- **Read-only** against BigQuery
- **Optional simple TTL cache** for hot aggregate queries (in-memory only, no Redis)
- **Request-level logging** for observability
- **No data processing** — all transformation happens in the ELT layer
- **No microservice splitting** — single deployable service

> **Future upgrade path:** If BigQuery query latency or cost becomes a concern at scale, a PostgreSQL-based serving store can be introduced as a materialized read replica of the aggregate and meta tables. This is not part of the current design scope.

---

### 14.1 Python FastAPI Serving Layer

**Module structure:**

| Package | Responsibility |
|---|---|
| `routers/` | Route definitions, endpoint handlers |
| `services/` | Business logic, query orchestration, cache interaction |
| `repositories/` | BigQuery client access, query execution |
| `schemas/` | Pydantic response/request models |
| `cache/` | In-memory cache implementation, TTL management |
| `config/` | Application settings, BigQuery client initialization |
| `health/` | Health and status endpoint implementations |
| `exceptions/` | Custom exception classes, error handlers |

**Technology:**
- Python 3.11+
- FastAPI
- Pydantic v2
- BigQuery Python client SDK
- `cachetools` or manual TTL dict (optional in-memory cache)

---

### 14.2 Local Deployment (Serving Layer)

The serving API runs as a **standalone process** outside the Airflow containers. The serving service reads the same `.env` file and GCP credentials as the rest of the project.

**Environment and credentials:**
- The serving service reads `GCP_PROJECT_ID`, `BQ_DATASET_MARTS`, `BQ_DATASET_META` from the project `.env` file (or equivalent environment variables)
- GCP authentication uses the same service account JSON key mounted at the path specified by `GOOGLE_APPLICATION_CREDENTIALS`
- The BigQuery client is initialized using Application Default Credentials — the service account key path must be set before the process starts
- Airflow run-metrics collection reads dbt execution metadata from `DBT_RUN_RESULTS_PATH`, which defaults to `/opt/airflow/dbt/target/run_results.json`

**Local startup:**
- Install: `cd serving-fastapi && uv sync`
- Run: `uvicorn app.main:app --host 0.0.0.0 --port 8090`
- Or via Docker: `docker build -t eia-serving-fastapi ./serving-fastapi && docker run --env-file .env -v $(pwd)/keys:/keys -p 8090:8090 eia-serving-fastapi`
- Default port: `8090` (configurable via `PORT` env var)
- Health check: `curl http://localhost:8090/health`

**BigQuery connection:**
- Initializes a BigQuery client using the service account key at the path specified by `GOOGLE_APPLICATION_CREDENTIALS`
- The client targets the project specified by `GCP_PROJECT_ID`
- All queries are scoped to the `marts` and `meta` datasets only — the serving layer never queries `raw` or `staging`

**Docker Compose integration (optional):**
- The serving service can be added to the project's `docker-compose.yml` as an additional service, but this is optional — it can also run standalone
- If added, it should mount the same `keys/` volume and read the same `.env` file

**Required `.env` variables for serving:**
```env
GCP_PROJECT_ID=your-gcp-project-id
GOOGLE_APPLICATION_CREDENTIALS=/path/to/keys/service-account.json
BQ_DATASET_MARTS=marts
BQ_DATASET_META=meta
PORT=8090  # optional, default 8090
```

---

## 15. Observability and Run Metrics

### Run Metrics Table
BigQuery table: `meta.run_metrics`

Fields:
- `run_id` (STRING) — Airflow `run_id`
- `dag_id` (STRING)
- `execution_date` (TIMESTAMP)
- `window_start` (TIMESTAMP) — start of the processed time window
- `window_end` (TIMESTAMP) — end of the processed time window
- `rows_loaded` (INT64)
- `dbt_models_passed` (INT64)
- `dbt_tests_passed` (INT64)
- `dbt_tests_failed` (INT64)
- `bytes_processed` (INT64) — from BigQuery job metadata
- `duration_seconds` (FLOAT64)
- `status` (STRING) — `success` | `failed`
- `created_at` (TIMESTAMP)

The `dbt_models_passed`, `dbt_tests_passed`, `dbt_tests_failed`, and `bytes_processed` fields are derived from the dbt `run_results.json` artifact located at `DBT_RUN_RESULTS_PATH`.

---

## 16. CI with GitHub Actions

### Workflows

| Workflow | Trigger | Steps |
|---|---|---|
| `lint.yml` | Push / PR | `sqlfluff lint` on dbt SQL, `ruff` on Python |
| `dbt_compile.yml` | Push / PR | `dbt deps && dbt parse --target ci --no-populate-cache` |
| `terraform_validate.yml` | Push / PR to `terraform/` | `terraform fmt -check`, `terraform validate` |

### CI dbt Profile

```yaml
voltage_hub:
  target: dev
  outputs:
    dev:
      type: bigquery
      method: service-account
      project: "{{ env_var('GCP_PROJECT_ID') }}"
      dataset: "{{ env_var('BQ_DATASET_STAGING', 'staging') }}"
      keyfile: "{{ env_var('GCP_SERVICE_ACCOUNT_KEY_PATH') }}"
      threads: 4
    ci:
      type: bigquery
      method: oauth
      project: "ci-placeholder"
      dataset: "ci_placeholder"
      threads: 1
```

CI validates syntax and code quality only — it does not connect to GCP or execute queries. For the BigQuery adapter, the CI dbt workflow uses offline `dbt parse` rather than `dbt compile` because `compile` may populate adapter caches and trigger warehouse introspection.

---

## 17. Verification Criteria

The following dimensions must be verified during development. Each is objectively testable.

### Infrastructure
- `terraform apply` provisions GCS bucket, BigQuery datasets (`raw`, `staging`, `marts`, `meta`), service account, and IAM without errors
- `terraform destroy` cleans up all resources
- Docker Compose starts all services; Airflow health endpoint responds healthy

### ELT Pipeline
- DAG appears in Airflow UI without import errors
- Incremental batch extraction completes successfully for a configured time window
- Raw data lands in GCS at the expected path
- `raw.eia_grid_batch` contains rows for the expected batch dates
- `dbt build` completes with 0 test failures
- `staging.stg_grid_metrics` contains canonicalized rows
- Mart tables (`fct_grid_metrics`, `dim_region`, `dim_energy_source`) are populated
- Aggregate tables contain rows for the expected periods
- `meta.pipeline_state` watermark is updated
- `meta.run_metrics` contains a row for each successful run
- Rerun / backfill of a previously completed window is idempotent (same result)

### Data Quality
- All dbt tests pass
- `dbt source freshness` reports `pass` or `warn`
- `meta.anomaly_results` is populated after runs

### Serving API
- Health endpoint responds `200`
- Freshness endpoint returns latest data timestamp and status
- Pipeline status endpoint returns latest run info
- Metric endpoints return valid, schema-conformant responses
- Responses include `data_as_of`, `pipeline_run_id`, and `freshness_status` metadata

### CI
- All CI workflows pass on clean PRs

---

## 18. Non-Functional Requirements

### 19.1 Performance

| Requirement | Target |
|---|---|
| Single batch run completion | < 15 minutes end-to-end |
| 7-day backfill total time | < 8 hours (sequential) |
| `dbt build` execution time | < 5 minutes (incremental) |
| Serving API response time | < 2 seconds (cached), < 5 seconds (uncached) |

### 19.2 Reliability

| Requirement | Detail |
|---|---|
| Task-level retries | 2 retries with 5-minute delay |
| API retries | 3 retries with backoff per task |
| DAG run timeout | 2 hours maximum |
| Idempotency | All tasks safe to re-run without data corruption |

### 19.3 Security

| Requirement | Detail |
|---|---|
| Credential storage | Service account key mounted as volume, never in image |
| `.gitignore` | Must include `keys/*.json`, `.env`, `terraform.tfstate*` |
| Service account permissions | Minimum: `bigquery.dataEditor`, `bigquery.jobUser`, `storage.objectAdmin` |
| Network | No public endpoints beyond `localhost:8080` (Airflow UI) and serving API local port |

### 19.4 Observability

| Requirement | Detail |
|---|---|
| Run metrics | Every run records to `meta.run_metrics` |
| Anomaly results | Every run records to `meta.anomaly_results` |
| Freshness | Tracked and exposed via both meta tables and serving API |
| Logs | Airflow UI; serving API request logs |

### 19.5 Maintainability

| Requirement | Detail |
|---|---|
| Code linting | SQL: `sqlfluff` (BigQuery dialect). Python: `ruff` |
| dbt documentation | Every model and column has a `description` in `schema.yml` |
| Terraform formatting | `terraform fmt` enforced in CI |

### 19.6 Cost Guardrails

| Requirement | Detail |
|---|---|
| BigQuery query budget | Analytical queries < 1 GB scanned (partition pruning) |
| GCS storage | Raw files retained for reproducibility; < $1/month at expected scale |
| No runaway backfill | `max_active_runs=1` prevents unbounded parallel execution |

---

## 19. Recommended Implementation Order

Development should proceed in the following phases:

1. **ELT backbone and warehouse layers** — Terraform infrastructure, Airflow DAG skeleton, GCS raw landing, BigQuery raw/staging/marts, dbt models and tests. This is the foundation everything else depends on.

2. **Meta layer, freshness, and anomaly detection** — `meta.pipeline_state`, `meta.run_metrics`, `meta.freshness_log`, `meta.anomaly_results`. Wire freshness checks and anomaly detection into the DAG.

3. **Serving layer** — Implement the serving API (FastAPI). Connect to marts and meta tables. Validate all endpoints against verification criteria.

---

## 20. Next Steps / Future Directions

### Visualization (Dashboard)

As a future step, an optional visualization layer (such as Tableau) can be introduced to connect to the mart datasets.

**Status**: Not part of the immediate implementation scope. Visualization is used for validating mart usability and optional visual exploration of the data product.

**Data Sources**:
- `marts.agg_load_daily`
- `marts.agg_load_hourly`
- `marts.agg_generation_mix`
- `marts.agg_top_regions`
- `meta.anomaly_results` (for operational indicators)

**Suggested Views**:
- Regional load trend (time series)
- Generation breakdown by energy source
- Top demand regions (ranked bar chart)
- Anomaly summary indicators

**Scope Note**: The visualization layer consumes the same marts and meta tables as the serving API. It does not require additional data models or aggregates.
