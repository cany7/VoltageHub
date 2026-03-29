# SETUP — VoltageHub

---

## 1. Purpose

This document explains how to configure, provision, run, and verify VoltageHub locally.

The root `README.md` is intentionally optimized for project overview and portfolio presentation. This setup guide is the operational companion for reproducible local execution.

---

## 2. Prerequisites

Before starting, make sure the following are available on your machine:

- A GCP project
- A service account JSON key with access to GCS and BigQuery
- An EIA API key
- Docker and Docker Compose
- Python 3.11
- `uv`
- Terraform 1.5+

Project baseline:

- GCP project ID: `voltage-hub-dev`
- Default region: `us-central1`
- Default raw bucket name: `voltage-hub-raw`

---

## 3. Repository Setup

Clone the repository and move into the project root:

```bash
git clone <your-repo-url>
cd voltage-hub
```

Review the example environment file before creating your local config:

```bash
cp .env.example .env
```

---

## 4. Environment Configuration

Fill in `.env` using the values appropriate for your environment.

The key variables are:

```env
# GCP
GCP_PROJECT_ID=voltage-hub-dev
GCP_REGION=us-central1
GCP_SERVICE_ACCOUNT_KEY_PATH=/opt/airflow/keys/service-account.json
GOOGLE_APPLICATION_CREDENTIALS=/opt/airflow/keys/service-account.json

# GCS
GCS_BUCKET_NAME=voltage-hub-raw

# BigQuery
BQ_DATASET_RAW=raw
BQ_DATASET_STAGING=staging
BQ_DATASET_MARTS=marts
BQ_DATASET_META=meta
BQ_DATASET_RAW_SAMPLE=raw_sample
BQ_DATASET_STAGING_SAMPLE=staging_sample
BQ_DATASET_MARTS_SAMPLE=marts_sample
BQ_DATASET_META_SAMPLE=meta_sample

# Airflow
AIRFLOW__CORE__EXECUTOR=LocalExecutor
AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=postgresql+psycopg2://airflow:airflow@postgres:5432/airflow
AIRFLOW__CORE__LOAD_EXAMPLES=False

# Pipeline
BACKFILL_DAYS=7
SAMPLE_MODE=false
DBT_RUN_RESULTS_PATH=/opt/airflow/dbt/target/run_results.json

# EIA
EIA_API_KEY=your-eia-api-key

# Serving API
PORT=8090
CACHE_TTL_SECONDS=300
```

Notes:

- `PORT` is the serving API port. Do not rename it to `SERVER_PORT`.
- `GCS_BUCKET_NAME` is the canonical raw bucket variable.
- `SAMPLE_MODE=true` routes the pipeline to isolated sample datasets instead of the primary warehouse datasets.

---

## 5. Credentials

Place your service account key at:

```text
keys/service-account.json
```

The project mounts that file into the containers at:

```text
/opt/airflow/keys/service-account.json
```

This means the following variables in `.env` should typically stay aligned:

```env
GCP_SERVICE_ACCOUNT_KEY_PATH=/opt/airflow/keys/service-account.json
GOOGLE_APPLICATION_CREDENTIALS=/opt/airflow/keys/service-account.json
```

If infrastructure is ever reprovisioned from scratch, make sure the service account key is still present in `keys/service-account.json` before restarting Docker Compose.

---

## 6. Provision Infrastructure

Initialize Terraform:

```bash
make terraform-init
```

Apply the infrastructure:

```bash
make terraform-apply
```

This provisions:

- A GCS bucket for raw landing
- BigQuery datasets: `raw`, `staging`, `marts`, `meta`
- The runtime service account and required IAM bindings

If you prefer running Terraform directly:

```bash
terraform -chdir=terraform init
terraform -chdir=terraform apply -var-file=terraform.tfvars
```

Verification targets:

- The raw bucket exists in GCS
- The four BigQuery datasets exist
- Terraform finishes without errors

Avoid destructive reprovision unless it is actually necessary. If you do need to recreate infrastructure, you may need to restore the service account key locally and restart Docker Compose so the containers remount it.

---

## 7. Start Local Services

Build and start the local stack:

```bash
make build
make up
```

Or with Docker Compose directly:

```bash
docker compose build
docker compose up -d
```

This starts:

- `postgres`
- `airflow-webserver`
- `airflow-scheduler`
- `serving-fastapi`

Default local URLs:

- Airflow UI: [http://localhost:8080](http://localhost:8080)
- FastAPI docs: [http://localhost:8090/docs](http://localhost:8090/docs)
- FastAPI health: [http://localhost:8090/health](http://localhost:8090/health)

Airflow default local credentials from the container bootstrap:

- Username: `admin`
- Password: `admin`

Quick container check:

```bash
docker compose ps
```

---

## 8. Prepare dbt

Run `dbt deps` before any dbt command:

```bash
make dbt-deps
```

This installs the dbt package dependencies inside the Airflow container.

You can then validate the warehouse project with:

```bash
make dbt-build BATCH_DATE=2026-03-27
```

Or generate docs with:

```bash
make dbt-docs
```

If you need to target sample mode manually, set `SAMPLE_MODE=true` in `.env` before running the DAG or dbt commands.

---

## 9. Run the Pipeline

The main DAG is:

```text
eia_grid_batch
```

You can trigger it from the Airflow UI, or run explicit backfill windows from the command line.

Example backfill with the Makefile:

```bash
make backfill START_DATE=2026-03-27T00:00:00+00:00 END_DATE=2026-03-28T00:00:00+00:00
```

Equivalent Docker command:

```bash
docker compose exec airflow-webserver airflow dags backfill eia_grid_batch \
  --start-date "2026-03-27T00:00:00+00:00" \
  --end-date "2026-03-28T00:00:00+00:00"
```

Each run performs the following sequence:

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

Airflow uses `catchup=True` and `max_active_runs=1`, so historical windows can be replayed sequentially without overlapping partition writes.

---

## 10. Start the Serving API

The serving API is already included in `docker compose up -d`, so for most local runs you do not need to start it separately.

If you want to run it outside Docker:

```bash
cd serving-fastapi
uv sync
uv run uvicorn app.main:app --host 0.0.0.0 --port 8090
```

Useful local checks:

```bash
curl http://localhost:8090/health
curl http://localhost:8090/pipeline/status
curl "http://localhost:8090/metrics/load?region=US48&start_date=2026-03-27&end_date=2026-03-27&granularity=daily"
```

---

## 11. Smoke Test

After the stack is up and at least one DAG run has completed, verify the system end to end.

### 11.1 Airflow

- The `eia_grid_batch` DAG appears in the UI
- A run completes without task failures
- The graph view shows all tasks in the expected sequence

### 11.2 GCS Raw Landing

Check that raw files land under the documented path pattern:

```text
gs://<bucket>/voltage-hub/raw/year=YYYY/month=MM/day=DD/window=<start_iso>/batch.json
```

### 11.3 BigQuery

Confirm that data exists in:

- `raw.eia_grid_batch`
- `staging.stg_grid_metrics`
- `marts.agg_load_daily`
- `marts.agg_generation_mix`
- `meta.pipeline_state`
- `meta.run_metrics`
- `meta.freshness_log`

### 11.4 Serving API

Verify key endpoints:

```bash
curl http://localhost:8090/health
curl http://localhost:8090/freshness
curl http://localhost:8090/pipeline/status
curl "http://localhost:8090/metrics/generation-mix?region=US48&start_date=2026-03-27&end_date=2026-03-27"
```

---

## 12. Sample Mode

Sample mode is intended for lightweight validation without writing to the primary warehouse datasets.

To enable it, set:

```env
SAMPLE_MODE=true
```

When sample mode is enabled:

- The DAG routes raw, staging, marts, and meta writes to the `*_sample` datasets
- dbt uses the `sample` target
- The scheduler-visible history is narrowed for lightweight validation

Sample mode still uses the same GCS bucket and raw object path convention. Isolation applies to BigQuery datasets and control-plane outputs rather than the landing bucket.

---

## 13. Verification Checklist

Use this checklist before considering the environment ready:

- Terraform apply completed successfully
- Docker Compose services are running
- Airflow UI loads on `localhost:8080`
- `dbt deps` completed successfully
- The DAG ran successfully for at least one window
- `raw`, `staging`, `marts`, and `meta` all contain data
- `/health` returns `200`
- `/freshness` returns both freshness signals
- `/pipeline/status` returns the latest successful window
- A metrics endpoint returns precomputed analytical results

---

## 14. Troubleshooting

### Credentials path errors

If Airflow or FastAPI cannot authenticate to GCP, confirm:

- `keys/service-account.json` exists locally
- `.env` points to `/opt/airflow/keys/service-account.json`
- The file is mounted into the containers

### IAM permission issues

If GCS uploads or BigQuery jobs fail, check that the runtime service account has the required roles:

- `bigquery.dataEditor`
- `bigquery.jobUser`
- `storage.objectAdmin`

### `dbt deps` not run

If dbt commands fail because packages are missing, run:

```bash
make dbt-deps
```

### DAG missing in Airflow

If `eia_grid_batch` does not appear in the Airflow UI:

- Confirm the containers are running
- Check `docker compose logs airflow-webserver`
- Check `docker compose logs airflow-scheduler`
- Confirm `airflow/dags/` is mounted correctly

### BigQuery datasets missing

If pipeline tasks fail because datasets do not exist, rerun Terraform apply and confirm the expected datasets are present.

### API returns empty data

If `/health` works but metrics endpoints return empty results:

- Confirm the DAG has completed successfully
- Confirm marts tables contain rows for the requested dates
- Confirm you are querying dates that actually exist in the warehouse

### Sample mode confusion

If results seem to be missing while `SAMPLE_MODE=true` is enabled, make sure you are checking the `*_sample` datasets rather than the primary datasets.

---

## 15. Related Documents

- `DOCS/SPEC.md`
- `DOCS/ARCHITECTURE.md`
- `DOCS/INTERFACES.md`
- `DOCS/TESTING.md`
- `CHANGELOG.md`
