[English](./README.md) | [简体中文](./DOCS/Docs_zh/README_zh.md)

# VoltageHub

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue)](./pyproject.toml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](./LICENSE)
[![Airflow](https://img.shields.io/badge/Airflow-2.8%2B-017CEE?logo=apacheairflow)](https://airflow.apache.org/)
[![dbt](https://img.shields.io/badge/dbt-1.7%2B-FF694B?logo=dbt)](https://www.getdbt.com/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688?logo=fastapi)](https://fastapi.tiangolo.com/)

An end-to-end batch analytics data product built on EIA grid operations data, with Airflow orchestration, a layered BigQuery warehouse, and a FastAPI serving layer.

## Overview

The U.S. Energy Information Administration (EIA) publishes operational data for the electric grid, covering generation, demand, and interchange across balancing authorities. VoltageHub uses this data to build a complete batch analytics data product that spans the core stages of a data engineering pipeline, from ingestion and warehouse modeling to API serving.

The goal is to turn raw EIA grid data into query-ready analytical tables and API endpoints. Data flows through GCS landing, BigQuery ingestion, and dbt's layered transformations before being served as curated metrics via FastAPI, with control-plane tables providing end-to-end observability.

## Project Highlights

- Time-window batch ELT with support for incremental sync, reruns, and historical backfill
- Raw landing in GCS ensures batch replayability, auditability, and decoupled reprocessing
- Layered BigQuery warehouse built with dbt, covering standardized modeling and precomputed analytics
- Partition-scoped incremental rebuilds keep reruns idempotent and limit downstream work to affected dates
- First-class observability outputs: pipeline state, run metrics, freshness tracking, and anomaly detection
- FastAPI serving layer backed by pre-aggregated warehouse tables rather than direct fact-table queries
- **Tech stack**: Airflow · BigQuery · dbt · FastAPI · GCS · Terraform · Docker · GitHub Actions

## Demo

The pictures below show the project running end to end, from orchestration through warehouse outputs to API serving.

### 1. Airflow DAG execution flow

![Airflow DAG execution flow](assets/Graph%20View.png)

The full orchestration graph, covering extraction, GCS landing, dbt builds, anomaly checks, and pipeline state updates.

### 2. Canonical staging model in BigQuery

![Canonical staging model in BigQuery](assets/Canonical%20staging%20model%20in%20BigQuery%20after%20dbt%20transformation.png)

Raw EIA records standardized into the staging layer after dbt transformation, providing a clean foundation for downstream marts and serving.

### 3. Precomputed daily regional load mart

![Precomputed daily regional load mart](assets/Precomputed%20analytical%20output%20for%20daily%20regional%20load%20in%20marts.png)

Precomputed daily regional load metrics in the mart layer, ready for downstream queries and API access.

### 4. FastAPI analytical endpoint

![FastAPI analytical endpoint](assets/FastAPI.png)

Analytical endpoints backed by precomputed warehouse outputs.

## Architecture

### System Architecture

```text
Source Layer
  -> EIA public grid data APIs

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

### Pipeline Flow

Each DAG run processes one time window derived from Airflow's scheduling context:

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

### Warehouse Layers

- `raw`: Source-shaped batch landing that preserves upstream EIA response structure for replay and auditability
- `staging`: Canonicalized and standardized grid metrics serving as a clean foundation for downstream modeling
- `marts`: Fact, dimension, and aggregate tables designed for analytical consumption and API serving
- `meta`: Control-plane tables tracking pipeline state, run metrics, freshness, and anomaly results

This layered design keeps ingestion, standardization, consumption, and observability responsibilities clearly separated.

## Pipeline Design

### Incremental and Backfill Strategy

The pipeline runs hourly, with each DAG run processing one Airflow time window.

Each run extracts source data for `data_interval_start` through `data_interval_end`, idempotently reloads the matching raw partition, and then rebuilds only the affected `observation_date` partitions in downstream staging and fact models. Small aggregate models are rebuilt as full tables to keep the implementation simple at the current scale.

`max_active_runs=1` is set intentionally to prevent overlapping partition writes and ensure deterministic reruns. A sample mode is also available for lightweight validation using isolated datasets and a separate dbt target.

### Data Quality and Observability

Data quality is enforced at three levels: dbt tests, source freshness checks, and post-build anomaly checks.

The project tracks pipeline freshness separately from data freshness, records per-run metrics in meta tables, and stores anomaly results as warning-only signals — unusual patterns are captured without blocking scheduled runs.

Control-plane outputs include:

- `meta.pipeline_state`: latest successful processing window
- `meta.run_metrics`: per-run operational metrics
- `meta.freshness_log`: pipeline and data freshness status
- `meta.anomaly_results`: anomaly summaries on key metrics

## Serving API

The API reads from pre-aggregated `marts.agg_*` tables and `meta.*` tables instead of running direct aggregations on large fact tables.

It exposes two categories of endpoints: operational endpoints (health, freshness, pipeline status) and analytical endpoints (load trends, generation mix, top-demand regions).

Each response includes metadata to help consumers interpret results in operational context:

- `data_as_of`
- `pipeline_run_id`
- `freshness_status`

## Quick Start

**Prerequisites**: GCP account with service account credentials, Docker, Terraform, Make, uv.

```bash
cp .env.example .env
make terraform-init
make terraform-apply
make build && make up
make dbt-deps
```

Then trigger `eia_grid_batch` in Airflow to run the pipeline, and query the API at `http://localhost:8090`.

For full environment setup, credentials, smoke tests, sample mode, and troubleshooting, see [SETUP.md](DOCS/SETUP.md).

## Project Layout

- `terraform/`: infrastructure as code for GCP resources
- `airflow/`: DAG definitions and orchestration logic
- `dbt/`: warehouse models, tests, and documentation
- `serving-fastapi/`: analytical API and query layer
- `tests/`: unit and integration tests
- `DOCS/`: development specs, architecture, interface definitions, and testing notes

## Dependencies and References

This project is built with the following tools and frameworks:

- [Apache Airflow](https://airflow.apache.org/): Workflow orchestration for batch ingestion, dbt execution, and control-plane updates.
- [BigQuery](https://cloud.google.com/bigquery): Analytical warehouse for `raw`, `staging`, `marts`, and `meta` datasets.
- [dbt Core](https://www.getdbt.com/) and [dbt-bigquery](https://docs.getdbt.com/docs/core/connect-data-platform/bigquery-setup): Warehouse transformations, tests, freshness checks, and documentation.
- [Docker](https://www.docker.com/) and [Docker Compose](https://docs.docker.com/compose/): Local development environment for Airflow and supporting services.
- [FastAPI](https://fastapi.tiangolo.com/): Serving layer for analytical and operational endpoints.
- [GitHub Actions](https://github.com/features/actions): CI/CD for linting, dbt validation, and Terraform checks.
- [Google Cloud Storage (GCS)](https://cloud.google.com/storage): Raw landing zone for replayable and auditable batch files.
- [Pydantic](https://docs.pydantic.dev/): Request and response validation for the API layer.
- [ruff](https://docs.astral.sh/ruff/) and [sqlfluff](https://docs.sqlfluff.com/): Python and SQL linting.
- [Terraform](https://www.terraform.io/): Infrastructure as code for GCP resources and IAM configuration.
- [uv](https://docs.astral.sh/uv/): Python dependency management and local command execution.

## License

This project is licensed under the Apache License 2.0 — see the `LICENSE` file for details.
