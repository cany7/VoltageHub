# Setup Guide — VoltageHub

---

## 1. Prerequisites

Ensure the following tools and credentials are available before proceeding:

| Requirement | Notes |
|---|---|
| GCP project | With billing enabled |
| Service account JSON key | Must have GCS + BigQuery access |
| EIA API key | Register at [EIA Open Data](https://www.eia.gov/opendata/) |
| Docker + Docker Compose | v2 CLI (`docker compose`) |
| Python 3.11 | Required for host-side linting and tests |
| `uv` | Python package manager ([docs](https://docs.astral.sh/uv/)) |
| Terraform 1.5+ | For GCP infrastructure provisioning |

**Project defaults** (used throughout this guide):

| Setting | Value |
|---|---|
| GCP project ID | `voltage-hub-dev` |
| Region | `us-central1` |
| Raw bucket | `voltage-hub-raw` |

---

## 2. Configuration

### 2.1 Clone and Create `.env`

```bash
git clone <your-repo-url>
cd voltage-hub
cp .env.example .env
```

### 2.2 Environment Variables

Open `.env` and fill in the values for your environment:

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

Key variables:

- **`PORT`** — Serving API port. Do not rename to `SERVER_PORT`.
- **`GCS_BUCKET_NAME`** — The canonical raw landing bucket.
- **`SAMPLE_MODE`** — Set to `true` to route all writes to isolated `*_sample` datasets (see [Appendix A](#appendix-a-sample-mode)).

### 2.3 Service Account Key

The runtime Service Account is created by Terraform in Section 3.1. **After completing Section 3.1**, manually perform the following:

1. Download the JSON key for this Service Account from the GCP Console.
2. Rename it to `service-account.json` and place it at:
   ```
   keys/service-account.json
   ```

Docker Compose mounts it into containers at `/opt/airflow/keys/service-account.json`. The two credential variables in `.env` should point to this container path.

---

## 3. Deploy and Launch

All operations use `make`. The Makefile wraps `docker compose` commands so there is no need to call Docker directly.

### 3.1 Provision Infrastructure (Terraform)

```bash
make terraform-init
make terraform-apply
```

This creates:

- A GCS bucket for raw data landing
- BigQuery datasets: `raw`, `staging`, `marts`, `meta`
- The runtime service account with required IAM bindings

### 3.2 Start Services

```bash
make build
make up
```

Four containers start:

| Service | URL |
|---|---|
| Airflow UI | [http://localhost:8080](http://localhost:8080) |
| FastAPI docs | [http://localhost:8090/docs](http://localhost:8090/docs) |
| FastAPI health | [http://localhost:8090/health](http://localhost:8090/health) |
| PostgreSQL | Internal (Airflow metadata DB) |

Airflow default credentials: `admin` / `admin`.

### 3.3 Install dbt Dependencies

```bash
make dbt-deps
```

Run this once before any dbt or pipeline operation. It installs dbt packages inside the Airflow container.

---

## 4. Run the Pipeline

### 4.1 Trigger the DAG

The main DAG is `eia_grid_batch`. Trigger it from the Airflow UI, or run a backfill from the command line:

```bash
make backfill START_DATE=2026-03-27T00:00:00+00:00 END_DATE=2026-03-28T00:00:00+00:00
```

Each run executes the following stages in order:

```
extract_grid_batch
→ land_raw_to_gcs
→ load_to_bq_raw
→ dbt_source_freshness
→ dbt_build
→ check_anomalies
→ record_run_metrics
→ update_pipeline_state
```

The DAG uses `catchup=True` and `max_active_runs=1`, so backfilled windows are processed sequentially without partition conflicts.

### 4.2 Serving API

The serving API (`serving-fastapi`) starts automatically with `make up`. No additional steps are needed for local use.

To run it outside Docker:

```bash
cd serving-fastapi
uv sync
uv run uvicorn app.main:app --host 0.0.0.0 --port 8090
```

Quick verification:

```bash
curl http://localhost:8090/health
curl http://localhost:8090/pipeline/status
curl "http://localhost:8090/metrics/load?region=US48&start_date=2026-03-27&end_date=2026-03-27&granularity=daily"
```

---

## 5. Verify

After at least one successful DAG run, confirm the following:

| Check | How |
|---|---|
| Terraform completed | `make terraform-apply` exited without errors |
| Services running | `make up` then `docker compose -f docker/docker-compose.yml ps` — all containers healthy |
| Airflow accessible | Open [http://localhost:8080](http://localhost:8080) |
| dbt deps installed | `make dbt-deps` exited without errors |
| DAG ran successfully | `eia_grid_batch` shows a completed run in the Airflow UI |
| BigQuery populated | `raw`, `staging`, `marts`, `meta` datasets contain data |
| `/health` | `curl http://localhost:8090/health` → `200` |
| `/freshness` | Returns `pipeline_freshness_timestamp` and `data_freshness_timestamp` |
| `/pipeline/status` | Returns latest successful window and `last_successful_run_id` |
| Metrics endpoint | Returns precomputed analytical results |

---

## 6. Testing

### 6.1 Test Paths Overview

The project has six test paths, controlled by environment variables:

| Path | Scope | When to Use | Connects to GCP? |
|---|---|---|---|
| **Unit Tests** | Extraction, loading, freshness, anomaly logic; Serving API routes and services | After every change | No |
| **E2E Smoke** | Single-window pipeline run → GCS → BigQuery → dbt → marts → meta; UTC date-boundary scenario | After pipeline-related changes | Yes |
| **E2E Heavy** | Idempotent rerun + multi-window backfill | Before milestone verification | Yes |
| **E2E Failure-Path** | Freshness warn-path + error-path using isolated temporary datasets | When validating failure handling | Yes |
| **Serving API Integration** | All FastAPI endpoints against real BigQuery data | After pipeline data is available | Yes |
| **CI** | Ruff + SQLFluff + unit tests + dbt parse + Terraform validate | Automatic on push / PR | No |

### 6.2 Unit Tests

```bash
uv run pytest tests/unit
```

Covers pipeline task logic (extraction, GCS path generation, BigQuery load config, retry behavior, freshness status, anomaly detection) and serving API unit tests (routes, services, validation). All mocked — no GCP access required.

### 6.3 E2E Tests

All three E2E paths live in `tests/integration/test_pipeline_e2e.py` and are controlled by environment variables.

**Smoke** (default integration path):

```bash
set -a; source .env; set +a
VOLTAGE_HUB_RUN_PIPELINE_TESTS=1 .venv/bin/pytest -rs tests/integration/test_pipeline_e2e.py
```

Runs a single-window extraction through the entire pipeline, plus a UTC date-boundary scenario. Suitable for daily regression.

**Heavy** (includes smoke):

```bash
set -a; source .env; set +a
VOLTAGE_HUB_RUN_PIPELINE_TESTS=1 \
VOLTAGE_HUB_RUN_HEAVY_PIPELINE_TESTS=1 \
  .venv/bin/pytest -rs tests/integration/test_pipeline_e2e.py
```

Adds idempotent rerun verification and multi-window backfill. Backfill defaults to 2 hourly windows. To adjust:

```bash
VOLTAGE_HUB_TEST_BACKFILL_HOURS=12    # Must be ≥ 2, integer
VOLTAGE_HUB_TEST_BACKFILL_END_BOUNDARY=2026-03-27T00:00:00+00:00  # Must align to full hour
```

Heavy tests preserve data in GCS/BigQuery (no cleanup). This data is useful for continued development.

**Failure-Path** (includes smoke):

```bash
set -a; source .env; set +a
VOLTAGE_HUB_RUN_PIPELINE_TESTS=1 \
VOLTAGE_HUB_RUN_FAILURE_PATH_PIPELINE_TESTS=1 \
  .venv/bin/pytest -rs tests/integration/test_pipeline_e2e.py
```

Creates isolated temporary BigQuery datasets, manipulates `_ingestion_timestamp` to trigger freshness warn and error paths, then automatically cleans up. Does not affect shared development data.

**Running all E2E paths together:**

```bash
set -a; source .env; set +a
VOLTAGE_HUB_RUN_PIPELINE_TESTS=1 \
VOLTAGE_HUB_RUN_HEAVY_PIPELINE_TESTS=1 \
VOLTAGE_HUB_RUN_FAILURE_PATH_PIPELINE_TESTS=1 \
  .venv/bin/pytest -rs tests/integration/test_pipeline_e2e.py
```

**Recommended order:**

1. Daily development → unit tests + E2E smoke
2. Milestone check → E2E heavy
3. Failure handling validation → E2E failure-path (can run independently)

### 6.4 Serving API Integration Tests

```bash
set -a; source .env; set +a
VOLTAGE_HUB_RUN_PIPELINE_TESTS=1 .venv/bin/pytest -rs tests/integration/test_serving_api.py
```

Requires populated BigQuery tables from a prior pipeline run. Tests all endpoints (`/health`, `/freshness`, `/pipeline/status`, `/anomalies`, `/metrics/*`) against real data, including response metadata validation and error handling.

### 6.5 CI

Three GitHub Actions workflows run automatically on push and PR:

| Workflow | What It Checks |
|---|---|
| **Lint** | Ruff + SQLFluff + pipeline unit tests + serving API unit tests |
| **dbt Parse** | `dbt deps` + `dbt parse --target ci` (offline, no GCP) |
| **Terraform Validate** | `terraform fmt -check` + `terraform validate` |

CI never connects to GCP. All checks are syntax and structural validation only.

---

## Appendix A: Sample Mode

Sample mode routes all pipeline writes to isolated `*_sample` BigQuery datasets for lightweight validation without affecting the primary warehouse.

Enable it in `.env`:

```env
SAMPLE_MODE=true
```

When enabled:

- The DAG writes to `raw_sample`, `staging_sample`, `marts_sample`, `meta_sample` instead of the primary datasets
- dbt uses the `sample` target
- Scheduler-visible history is narrowed for quicker runs

Sample mode still uses the same GCS bucket and raw landing path. Isolation applies to BigQuery datasets only.

---

## Appendix B: Troubleshooting

**Credentials path errors**
Confirm `keys/service-account.json` exists locally and `.env` points to `/opt/airflow/keys/service-account.json`. Check that the file is mounted: `docker compose -f docker/docker-compose.yml ps` should show healthy containers.

**IAM permission failures**
The runtime service account needs: `bigquery.dataEditor`, `bigquery.jobUser`, `storage.objectAdmin`.

**dbt commands fail with missing packages**
Run `make dbt-deps` before any dbt operation.

**DAG missing in Airflow UI**
Check container logs: `docker compose -f docker/docker-compose.yml logs airflow-webserver` and `docker compose -f docker/docker-compose.yml logs airflow-scheduler`. Confirm `airflow/dags/` is mounted correctly.

**BigQuery datasets missing**
Re-run `make terraform-apply` and confirm the datasets exist in the GCP console.

**API returns empty data**
Ensure at least one DAG run completed successfully and that the queried date range matches data present in the marts tables.

**Sample mode confusion**
When `SAMPLE_MODE=true`, all reads and writes go to `*_sample` datasets. Check the sample datasets, not the primary ones.

---

## Related Documents

- [SPEC.md](SPEC.md)
- [ARCHITECTURE.md](ARCHITECTURE.md)
- [INTERFACES.md](INTERFACES.md)
- [TESTING.md](TESTING.md)
- [CHANGELOG.md](CHANGELOG.md)
