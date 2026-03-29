# VoltageHub

An end-to-end batch analytics data product built on EIA grid operations data, with Airflow orchestration, a layered BigQuery warehouse, and a FastAPI serving layer.

## Overview

VoltageHub turns raw EIA grid operations data into query-ready analytical tables and API endpoints.

Instead of querying the upstream source directly, the pipeline ingests data in scheduled time windows, lands raw batches in GCS for replayable reprocessing, loads source-shaped records into BigQuery, transforms them with dbt across `raw`, `staging`, `marts`, and `meta` layers, and exposes curated metrics through FastAPI. It also records freshness, run metrics, and anomaly results in meta tables.

## Project Highlights

- Time-window batch ELT with support for incremental sync, reruns, and historical backfill
- Raw landing in Google Cloud Storage for replayability, auditability, and decoupled reprocessing
- Layered BigQuery warehouse built with dbt for standardized modeling and precomputed analytics
- Partition-scoped incremental rebuilds to keep reruns idempotent and limit downstream work to affected dates
- First-class operational outputs for pipeline freshness, anomaly detection, run metrics, and pipeline state
- FastAPI serving layer backed by pre-aggregated warehouse tables rather than raw or fact-level queries

## Architecture

```text
Source Layer
  -> EIA public grid data interfaces

Orchestration Layer
  -> Airflow DAG scheduling
  -> time-window batch execution
  -> incremental sync and backfill

Raw Data Layer
  -> GCS raw landing
  -> replayable batch files
  -> BigQuery raw ingestion

Transformation Layer
  -> dbt staging canonicalization
  -> fact, dimension, and aggregate models
  -> partition-scoped incremental rebuilds

Control Plane Layer
  -> pipeline state
  -> run metrics
  -> freshness tracking
  -> anomaly results

Serving Layer
  -> FastAPI analytical endpoints
  -> health, freshness, pipeline status
  -> metrics and anomaly access
```

Airflow orchestrates ingestion, GCS and BigQuery handle raw landing and storage, dbt builds the warehouse, and FastAPI serves curated outputs from marts and meta tables.

## Pipeline Flow

Each DAG run processes one time window derived from Airflow's scheduling context.

```text
extract_grid_batch
-> land_raw_to_gcs
-> load_to_bq_raw
-> dbt_source_freshness
-> dbt_build
-> check_anomalies
-> record_run_metrics
-> update_pipeline_state
```

Airflow coordinates the workflow, while the core transformation and analytical computation happen in BigQuery through dbt models and post-build checks.

## Warehouse Layers

- `raw`: Source-shaped batch landing that preserves the structure of the upstream EIA response for replay and auditability
- `staging`: Canonicalized and standardized grid metrics used as the clean foundation for downstream modeling
- `marts`: Fact, dimension, and aggregate tables designed for analytical consumption and API serving
- `meta`: Control-plane tables that track pipeline state, run metrics, freshness, and anomaly results

This layered design keeps ingestion, standardization, consumption, and observability responsibilities clearly separated.

## Incremental and Backfill Strategy

The pipeline runs hourly and processes one Airflow time window per DAG run.

For each run, it extracts the source data for `data_interval_start` to `data_interval_end`, reloads the matching raw partition idempotently, and then rebuilds only the affected `observation_date` partitions in downstream staging and fact models.

Small aggregate models are rebuilt as full tables to keep the implementation simple at the current project scale. `max_active_runs=1` is intentionally used to avoid overlapping partition writes and keep reruns deterministic.

Sample mode is also available for lightweight validation using isolated datasets and a separate dbt target.

## Data Quality and Observability

Data quality is enforced through dbt tests, source freshness checks, and post-build anomaly checks.

The project tracks pipeline freshness separately from data freshness, records per-run metrics in meta tables, and stores anomaly results as warning-only signals so unusual patterns are visible without breaking scheduled runs.

Control-plane outputs include:

- `meta.pipeline_state` for the latest successful processing window
- `meta.run_metrics` for per-run operational metrics
- `meta.freshness_log` for pipeline and data freshness status
- `meta.anomaly_results` for anomaly summaries on key metrics

## Serving API

The API reads from pre-aggregated `marts.agg_*` tables and `meta.*` tables instead of running direct aggregations on large fact tables.

It exposes operational endpoints such as health, freshness, and pipeline status, along with analytical endpoints for load trends, generation mix, and top-demand regions.

Responses include metadata that helps consumers interpret results in operational context:

- `data_as_of`
- `pipeline_run_id`
- `freshness_status`

## Quick Start

```bash
cp .env.example .env
make terraform-init
make terraform-apply
make build && make up
make dbt-deps
```

Then trigger `eia_grid_batch` in Airflow and query the API at `http://localhost:8090`.

For full environment setup, credentials, smoke tests, sample mode, and troubleshooting, see `DOCS/SETUP.md`.

## Demo

The screenshots below show the project running end to end, from orchestration to warehouse outputs to API serving.

### 1. Airflow DAG execution flow

![Airflow DAG execution flow](assets/Graph%20View.png)

Shows the end-to-end DAG orchestration, from extraction and raw landing through dbt builds, anomaly checks, and pipeline state updates.

### 2. Canonical staging model in BigQuery

![Canonical staging model in BigQuery](assets/Canonical%20staging%20model%20in%20BigQuery%20after%20dbt%20transformation.png)

Shows raw EIA records standardized into the canonical staging layer that feeds downstream marts and serving.

### 3. Precomputed daily regional load mart

![Precomputed daily regional load mart](assets/Precomputed%20analytical%20output%20for%20daily%20regional%20load%20in%20marts.png)

Shows precomputed daily regional load metrics in the mart layer, ready for downstream queries and API access.

### 4. FastAPI analytical endpoint

![FastAPI analytical endpoint](assets/FastAPI.png)

Shows the serving layer exposing predefined analytical endpoints backed by warehouse outputs.

## Project Layout

- `terraform/`: infrastructure as code for GCP resources
- `airflow/`: DAGs and orchestration logic
- `dbt/`: warehouse models, tests, and documentation
- `serving-fastapi/`: analytical API and query layer
- `tests/`: unit and integration tests
- `DOCS/`: specifications, architecture, interfaces, and testing notes

## Tech Stack

This project is built with the following tools and frameworks:

- [Apache Airflow](https://airflow.apache.org/): Workflow orchestration for batch ingestion, dbt execution, and pipeline control-plane updates.
- [BigQuery](https://cloud.google.com/bigquery): Analytical warehouse for raw, staging, marts, and meta datasets.
- [dbt Core](https://www.getdbt.com/) and [dbt-bigquery](https://docs.getdbt.com/docs/core/connect-data-platform/bigquery-setup): Warehouse transformations, tests, freshness checks, and documentation.
- [Docker](https://www.docker.com/) and [Docker Compose](https://docs.docker.com/compose/): Local development environment for Airflow and supporting services.
- [FastAPI](https://fastapi.tiangolo.com/): Serving layer for analytical and operational endpoints.
- [GitHub Actions](https://github.com/features/actions): CI for linting, dbt validation, and Terraform checks.
- [Google Cloud Storage](https://cloud.google.com/storage): Raw landing zone for replayable and auditable batch files.
- [Pydantic](https://docs.pydantic.dev/): Request and response validation for the API layer.
- [ruff](https://docs.astral.sh/ruff/) and [sqlfluff](https://docs.sqlfluff.com/): Python and SQL linting.
- [Terraform](https://www.terraform.io/): Infrastructure as code for GCP resources and IAM configuration.
- [uv](https://docs.astral.sh/uv/): Python dependency management and local command execution.

## License

This project is licensed under the Apache License 2.0. See the `LICENSE` file for details.
