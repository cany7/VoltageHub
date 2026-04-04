# Setup Guide — VoltageHub

---

## 1. Clone the Repo

```bash
git clone <your-repo-url>
cd voltage-hub
cp .env.example .env
```

---

## 2. Configure `.env`

Set the following required values in `.env`:

- `GCP_PROJECT_ID` — GCP project used by Terraform, Airflow, and the serving layer
- `GCS_BUCKET_NAME` — GCS bucket for raw data landing; the name must be globally unique
- `EIA_API_KEY` — API key for EIA data ingestion

All other variables in `.env.example` are optional.

---

## 3. Provision Infrastructure (Terraform)

```bash
make terraform-init
make terraform-apply
```

This step creates the GCS bucket, the BigQuery datasets, and the runtime service account.

---

## 4. Download the Service Account Key

After Terraform finishes, download the runtime service account JSON key from GCP and place it in `keys/`.

Rename the file to:

```text
keys/service-account.json
```

If you use MCP, set `MCP_GOOGLE_APPLICATION_CREDENTIALS` to the file's absolute path on your host machine.

---

## 5. Start Docker Services

```bash
make build
make up
```

Services:

| Service | URL |
|---|---|
| Airflow UI | [http://localhost:8080](http://localhost:8080) |
| FastAPI docs | [http://localhost:8090/docs](http://localhost:8090/docs) |
| FastAPI health | [http://localhost:8090/health](http://localhost:8090/health) |
| PostgreSQL | Internal (Airflow metadata DB) |

Airflow default credentials: `admin` / `admin`.

---

## 6. Run the Pipeline

The main DAG is `eia_grid_batch`. Trigger it from the Airflow UI, or run a backfill:

```bash
make backfill START_DATE=2026-03-27T00:00:00+00:00 END_DATE=2026-03-28T00:00:00+00:00
```

---

## 7. Optional: MCP Server

The MCP server runs as a **stdio** process for AI agent applications.

Install dependencies and start it from `mcp/`:

```bash
cd mcp
uv sync
uv run voltagehub-mcp
```

Example configuration:

```json
{
  "mcpServers": {
    "voltagehub": {
      "command": "uv",
      "args": ["run", "voltagehub-mcp"],
      "cwd": "/absolute/path/to/voltage-hub/mcp",
      "env": {
        "MCP_GCP_PROJECT_ID": "voltage-hub-dev",
        "MCP_GOOGLE_APPLICATION_CREDENTIALS": "/absolute/path/to/voltage-hub/keys/service-account.json"
      }
    }
  }
}
```

Set `MCP_GCP_PROJECT_ID` and `MCP_GOOGLE_APPLICATION_CREDENTIALS` either in `.env` or in your MCP application config. `MCP_GOOGLE_APPLICATION_CREDENTIALS` should point to the absolute host path of `keys/service-account.json`.

---

## 8. Testing

### 8.1 Test Paths Overview

The project has eight test paths, controlled by environment variables where applicable:

| Path | Scope | When to Use | Connects to GCP? |
|---|---|---|---|
| **Unit Tests** | Extraction, loading, freshness, anomaly logic; Serving API routes and services | After every change | No |
| **CI** | Ruff + SQLFluff + unit tests + dbt parse + Terraform validate | Automatic on push / PR | No |
| **MCP Tests** | MCP settings, adapter contracts, server registration, stdio E2E behavior | After MCP-related changes | No |
| **Sample Mode** | Writes pipeline output to isolated `*_sample` datasets | Lightweight validation without affecting primary datasets | Yes |
| **E2E Smoke** | Single-window pipeline run → GCS → BigQuery → dbt → marts → meta; UTC date-boundary scenario | After pipeline-related changes | Yes |
| **E2E Heavy** | Idempotent rerun + multi-window backfill | Before milestone verification | Yes |
| **E2E Failure-Path** | Freshness warn-path + error-path using isolated temporary datasets | When validating failure handling | Yes |
| **Serving API Integration** | All FastAPI endpoints against real BigQuery data | After pipeline data is available | Yes |

### 8.2 Unit Tests

```bash
uv run pytest tests/unit
```

Covers pipeline task logic (extraction, GCS path generation, BigQuery load config, retry behavior, freshness status, anomaly detection) and serving API unit tests (routes, services, validation). All tests are mocked; no GCP access is required.

### 8.3 CI

Three GitHub Actions workflows run automatically on push and PR:

| Workflow | What It Checks |
|---|---|
| **Lint** | Ruff + SQLFluff + pipeline unit tests + serving API unit tests + MCP tests |
| **dbt Parse** | `dbt deps` + `dbt parse --target ci` (offline, no GCP) |
| **Terraform Validate** | `terraform fmt -check` + `terraform validate` |

CI never connects to GCP. All checks are syntax and structural validation only.

### 8.4 MCP Tests

```bash
cd mcp
uv sync --dev
uv run pytest -q tests
```

Covers MCP-specific settings loading, adapter contracts, documented tool and resource registration, and stdio end-to-end behavior. These tests run locally with stubs and do not require GCP access.

### 8.5 Sample Mode

Sample mode redirects pipeline writes to isolated `*_sample` BigQuery datasets, letting you validate changes without affecting the primary warehouse.

Enable it in `.env`:

```env
SAMPLE_MODE=true
```

When enabled:

- The DAG writes to `raw_sample`, `staging_sample`, `marts_sample`, and `meta_sample`
- dbt uses the `sample` target
- Scheduler-visible history is narrowed for shorter validation runs

Sample mode still uses the same GCS bucket and raw landing path. Isolation applies only to BigQuery datasets.

### 8.6 E2E Tests

All three E2E paths live in `tests/integration/test_pipeline_e2e.py` and are enabled through environment variables.

**Smoke** (default integration path):

```bash
set -a; source .env; set +a
VOLTAGE_HUB_RUN_PIPELINE_TESTS=1 .venv/bin/pytest -rs tests/integration/test_pipeline_e2e.py
```

Runs a single-window extraction through the full pipeline, plus a UTC date-boundary scenario. It is well suited for day-to-day regression checks.

**Heavy** (includes smoke):

```bash
set -a; source .env; set +a
VOLTAGE_HUB_RUN_PIPELINE_TESTS=1 \
VOLTAGE_HUB_RUN_HEAVY_PIPELINE_TESTS=1 \
  .venv/bin/pytest -rs tests/integration/test_pipeline_e2e.py
```

Adds idempotent rerun verification and multi-window backfill testing. Backfill uses 2 hourly windows by default. To adjust it:

```bash
VOLTAGE_HUB_TEST_BACKFILL_HOURS=12    # Integer, >= 2
VOLTAGE_HUB_TEST_BACKFILL_END_BOUNDARY=2026-03-27T00:00:00+00:00  # Align to a full hour
```

Heavy tests keep the generated data in GCS and BigQuery instead of cleaning it up automatically. That retained data can be useful for continued development.

**Failure-Path** (includes smoke):

```bash
set -a; source .env; set +a
VOLTAGE_HUB_RUN_PIPELINE_TESTS=1 \
VOLTAGE_HUB_RUN_FAILURE_PATH_PIPELINE_TESTS=1 \
  .venv/bin/pytest -rs tests/integration/test_pipeline_e2e.py
```

Creates isolated temporary BigQuery datasets, modifies `_ingestion_timestamp` to trigger freshness warn and error paths, and then cleans everything up automatically. It does not affect shared development data.

**Execution order:**

1. Daily development → unit tests + E2E smoke
2. Milestone check → E2E heavy
3. Failure handling validation → E2E failure-path (can run independently)

### 8.7 Serving API Integration Tests

```bash
set -a; source .env; set +a
VOLTAGE_HUB_RUN_PIPELINE_TESTS=1 .venv/bin/pytest -rs tests/integration/test_serving_api.py
```

Requires populated BigQuery tables from a prior pipeline run. Tests all endpoints (`/health`, `/freshness`, `/pipeline/status`, `/anomalies`, `/metrics/*`) against real data, including response metadata validation and error handling.

### 8.8 Serving API Latency Benchmark

```bash
set -a; source .env; set +a
uv run python tests/rest_api_latency_benchmark.py --base-url http://127.0.0.1:8090
```

The benchmark uses real BigQuery data to auto-select valid parameters and drives the API with `curl`. Pass `--restart-command "<your restart command>"` if you want a true cold-start reset between endpoints.

---

## 9. Troubleshooting

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
Ensure that at least one DAG run has completed successfully and that the queried date range matches data available in the marts tables.

**Sample mode confusion**
When `SAMPLE_MODE=true`, all reads and writes go to `*_sample` datasets. Check the sample datasets, not the primary ones.

---
