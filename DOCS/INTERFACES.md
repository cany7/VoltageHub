# INTERFACES.md — VoltageHub

---

## 1. Serving Interfaces

The serving layer is a read-only, fixed-template query facade exposed through REST and MCP interfaces. All serving outputs return pre-computed results from aggregate, meta, or serving-safe dimension tables. No runtime heavy aggregation.

**MCP precedence note:** `DOCS/MCP.md` defines the authoritative MCP tool/resource contract. This document records only the stable system-level MCP interface summary and its alignment with REST capabilities, table contracts, and metadata semantics.

### 1.1 REST Control Plane Endpoints

#### GET /health

- **Purpose:** Service-level liveness check. No BigQuery dependency.
- **Parameters:** None
- **Response:**
  - `status`: `"healthy"`
  - HTTP 200

#### GET /freshness

- **Purpose:** Returns latest pipeline and data freshness signals.
- **Source table:** `meta.freshness_log`
- **Parameters:** None
- **Response fields:**
  - `pipeline_freshness_timestamp` (ISO timestamp) — `MAX(_ingestion_timestamp)` from raw
  - `data_freshness_timestamp` (ISO timestamp) — `MAX(observation_timestamp)` from staging
  - `pipeline_freshness_status` — `"fresh"` | `"stale"`
  - `data_freshness_status` — `"fresh"` | `"stale"`
  - `freshness_status` — combined: worse of the two signals (`"fresh"` | `"stale"` | `"unknown"`)
  - `checked_at` (ISO timestamp)
- **Failure behavior:** Returns `"unknown"` status if no freshness records exist.

#### GET /pipeline/status

- **Purpose:** Returns latest successful pipeline sync info.
- **Source table:** `meta.pipeline_state`
- **Parameters:** None
- **Response fields:**
  - `pipeline_name` (string)
  - `last_successful_window_start` (ISO timestamp)
  - `last_successful_window_end` (ISO timestamp)
  - `last_successful_run_id` (string)
  - `updated_at` (ISO timestamp)
- **Failure behavior:** Returns empty/null fields if pipeline has never run.

#### GET /anomalies

- **Purpose:** Returns recent anomaly detection results.
- **Source table:** `meta.anomaly_results`
- **Parameters:**
  - `region` (string, optional) — filter by region
  - `start_date` (date, optional) — filter start
  - `end_date` (date, optional) — filter end
  - `anomaly_only` (boolean, optional, default: true) — if true, return only flagged anomalies
- **Response fields (per item):**
  - `observation_date` (date)
  - `region` (string)
  - `metric_name` (string)
  - `current_value` (float)
  - `rolling_7d_avg` (float)
  - `pct_deviation` (float)
  - `anomaly_flag` (boolean)
  - `checked_at` (ISO timestamp)

### 1.2 REST Metric Endpoints

All metric endpoint responses include these metadata fields:

- `data_as_of` (ISO timestamp) — latest `data_freshness_timestamp` from `meta.freshness_log`
- `pipeline_run_id` (string) — from `meta.pipeline_state.last_successful_run_id`
- `freshness_status` — combined status: `"fresh"` | `"stale"` | `"unknown"`

#### GET /metrics/load

- **Purpose:** Load/demand metrics by region and time granularity.
- **Source table:** `marts.agg_load_hourly` (granularity=hourly) or `marts.agg_load_daily` (granularity=daily)
- **Parameters:**
  - `region` (string, required) — balancing area code
  - `start_date` (date, required) — range start
  - `end_date` (date, required) — range end
  - `granularity` (string, required) — `"hourly"` | `"daily"`
- **Response:** List of load metric records for the region + time range
- **Invariants:**
  - Only predefined filters (region, date range, granularity)
  - No runtime aggregation; rows returned as-is from aggregate table
- **Failure behavior:** 400 if region or dates invalid; empty list if no data in range

#### GET /metrics/generation-mix

- **Purpose:** Generation breakdown by energy source for a region and time range.
- **Source table:** `marts.agg_generation_mix`
- **Parameters:**
  - `region` (string, required)
  - `start_date` (date, required)
  - `end_date` (date, required)
- **Response:** List of generation records by energy source, each with region, observation_date, energy_source, and metric values
- **Invariants:**
  - Grain: region × observation_date × energy_source
  - No broader time-window aggregation at runtime
- **Failure behavior:** 400 if parameters invalid; empty list if no data

#### GET /metrics/top-regions

- **Purpose:** Per-day top regions by total demand. Returns the pre-computed daily ranking for each day in the requested range — **not** a cross-day aggregate.
- **Source table:** `marts.agg_top_regions`
- **Parameters:**
  - `start_date` (date, required)
  - `end_date` (date, required)
  - `limit` (integer, optional, default: 10) — top N **per `observation_date`**
- **Response:** List of records, each containing `observation_date`, `region`, `region_name`, `daily_total_load`, and `rank`. Ordered by `observation_date ASC, rank ASC`.
- **Invariants:**
  - Grain: `observation_date × region`
  - `limit` applies per day: for each `observation_date` in the range, return at most `limit` rows
  - Ranking and `daily_total_load` are pre-computed in dbt; the API only applies `WHERE` + `LIMIT` filters — no runtime aggregation
  - No cross-day summarization or re-ranking at query time
- **Failure behavior:** 400 if dates invalid; empty list if no data in range

### 1.3 MCP Tools

MCP is a first-class serving interface exposed over `stdio`. It is not an HTTP wrapper and must not call the REST API over HTTP. MCP shares core business semantics with REST, but may add adapter-level safety semantics for agent use. Detailed MCP behavior, defaults, normalization rules, overflow behavior, and response shaping are defined in `DOCS/MCP.md`.

#### `get_load_trends`

- **Backed by REST capability:** `GET /metrics/load`
- **Purpose:** Region-specific load trends over a date range
- **Stable semantics:**
  - same analytical capability as REST load metrics
  - date filtering is on `observation_date`, inclusive on both bounds
  - supports `daily` and `hourly` views through MCP adapter-level parameter translation

#### `get_generation_mix`

- **Backed by REST capability:** `GET /metrics/generation-mix`
- **Purpose:** Region-specific generation mix over a date range
- **Stable semantics:**
  - grain remains `region × observation_date × energy_source`
  - if percentage support is enabled, it is a row-level per-day, per-region derived field only
  - it does not imply whole-period composition

#### `get_top_demand_regions`

- **Backed by REST capability:** `GET /metrics/top-regions`
- **Purpose:** Per-day top-demand regional ranking in a date range
- **Stable semantics:**
  - returns pre-computed daily rankings only
  - it does not provide whole-period cumulative ranking
  - equivalent REST meaning uses `limit` per `observation_date`; MCP may expose `top_n`

#### `check_data_freshness`

- **Backed by REST capability:** `GET /freshness`
- **Purpose:** Current pipeline/data freshness state for analytical trust checks

#### `get_anomalies`

- **Backed by REST capability:** `GET /anomalies`
- **Purpose:** Recent anomaly detection results with optional filtering
- **Stable semantics:**
  - output preserves `anomaly_flag`
  - canonical MCP parameter naming may use `anomaly_only`

#### `get_pipeline_status`

- **Backed by REST capability:** `GET /pipeline/status`
- **Purpose:** Latest successful pipeline window and update state

### 1.4 MCP Resources

#### `schema://grid-metrics`

- **Purpose:** Machine-readable discovery resource for MCP tools, defaults, limits, ordering, and supported metric concepts
- **Notes:** Available date bounds may be derived from serving-safe aggregate tables; detailed shape is defined in `DOCS/MCP.md`

#### `status://data-quality`

- **Purpose:** Current operational context for freshness, pipeline state, and anomaly summary
- **Notes:** Recent anomaly summary is anchored to the latest available `observation_date` in `meta.anomaly_results`

#### `schema://regions`

- **Purpose:** Canonical region discovery for MCP queries
- **Guaranteed fields in v1:** `region`, `region_name`
- **Scope note:** alias metadata is out of scope for v1

#### `schema://energy-sources`

- **Purpose:** Canonical energy-source discovery for generation-mix queries
- **Guaranteed fields in v1:** `energy_source`
- **Scope note:** richer semantic fields are out of scope for v1 unless the dimension schema expands

### 1.5 MCP Common Response and Error Semantics

Common MCP tool response envelope:

```
{
  "summary": { ... },
  "highlights": [ ... ],
  "data": [ ... ],
  "metadata": { ... }
}
```

Metadata notes:
- includes REST-aligned metadata semantics for `data_as_of`, `pipeline_run_id`, and `freshness_status`
- may include MCP-only safety metadata such as truncation markers or source-table hints

Error categories:
- `validation_error`
- `unsupported_capability`
- `repository_error`

Normalization and scope notes:
- region normalization supports canonical `region` and exact case-insensitive `region_name`
- aliases are out of scope for v1
- detailed MCP defaults, limits, truncation behavior, and normalization rules defer to `DOCS/MCP.md`

---

## 2. BigQuery Table Contracts

### 2.1 Raw Layer

#### raw.eia_grid_batch

| Column                | Type      | Nullable | Notes                                        |
|-----------------------|-----------|----------|----------------------------------------------|
| `respondent`          | STRING    | No       | Balancing authority identifier               |
| `respondent_name`     | STRING    | No       | Human-readable name                          |
| `type`                | STRING    | No       | Response category (demand, generation, etc.) |
| `type_name`           | STRING    | No       | Human-readable type label                    |
| `value`               | FLOAT64   | No       | Reported value                               |
| `value_units`         | STRING    | No       | Unit of measurement                          |
| `period`              | STRING    | No       | Observation period (ISO timestamp/date)      |
| `fueltype`            | STRING    | Yes      | Fuel type code (generation data only)        |
| `fueltype_name`       | STRING    | Yes      | Human-readable fuel type label               |
| `batch_date`          | DATE      | No       | Extraction batch date (partition key)        |
| `_batch_id`           | STRING    | No       | Extraction batch identifier                  |
| `_source_url`         | STRING    | No       | Source endpoint URL                          |
| `_ingestion_timestamp`| TIMESTAMP | No       | Pipeline-generated, used for freshness       |

**Partitioned by:** `batch_date`

### 2.2 Staging Layer

#### staging.stg_grid_metrics

| Column                  | Type      | Nullable | Notes                                              |
|-------------------------|-----------|----------|----------------------------------------------------|
| `metric_surrogate_key`  | STRING    | No       | `dbt_utils.generate_surrogate_key(...)` — PK       |
| `region`                | STRING    | No       | Standardized region code                           |
| `region_name`           | STRING    | No       | Human-readable region name                         |
| `observation_timestamp` | TIMESTAMP | No       | Parsed from `period`                               |
| `observation_date`      | DATE      | No       | Derived from `observation_timestamp` (partition key) |
| `metric_name`           | STRING    | No       | Standardized metric type                           |
| `metric_value`          | FLOAT64   | No       | Reported value                                     |
| `energy_source`         | STRING    | Yes      | Standardized fuel type; allowed Voltage Hub codes: `BAT`, `BIO`, `COL`, `GEO`, `HPS`, `HYC`, `NG`, `NUC`, `OES`, `OIL`, `OTH`, `PS`, `SNB`, `SUN`, `UES`, `UNK`, `WAT`, `WNB`, `WND` |
| `unit`                  | STRING    | No       | Standardized unit                                  |
| `_ingestion_timestamp`  | TIMESTAMP | No       | Passed through from raw                            |

**Partitioned by:** `observation_date`
**Clustered by:** `region`, `metric_name`

### 2.3 Marts Layer

#### marts.fct_grid_metrics

- One row per: region × observation_timestamp × metric_name × energy_source
- Partitioned by `observation_date`, clustered by `region`, `metric_name`

#### marts.dim_region

- `region` (STRING, PK), `region_name` (STRING)
- Supports MCP schema resources and region normalization support
- Do not assume alias fields unless the dimension schema is explicitly expanded

#### marts.dim_energy_source

- `energy_source` (STRING, PK), optional category grouping fields
- Supports MCP schema resources
- Do not assume labels, descriptions, or categories in MCP v1 unless the dimension schema is explicitly expanded

#### marts.agg_load_hourly

- Hourly load/demand by region

#### marts.agg_load_daily

- Daily load by region: avg, min, max, total

#### marts.agg_generation_mix

- Grain: region × observation_date × energy_source

#### marts.agg_top_regions

| Column             | Type    | Notes                                       |
|--------------------|---------|---------------------------------------------|
| `observation_date` | DATE    | Partition key                               |
| `region`           | STRING  |                                             |
| `region_name`      | STRING  |                                             |
| `daily_total_load` | FLOAT64 | Sum of load for the region on this date     |
| `rank`             | INT64   | Rank within this `observation_date` (1 = highest load) |

- Grain: `observation_date × region`, ranked by `daily_total_load` descending per date

### 2.4 Meta Layer

#### meta.pipeline_state

Created on demand by Airflow before write operations if the table does not already exist.

| Column                          | Type      | Notes                                  |
|---------------------------------|-----------|----------------------------------------|
| `pipeline_name`                 | STRING    |                                        |
| `last_successful_window_start`  | TIMESTAMP |                                        |
| `last_successful_window_end`    | TIMESTAMP |                                        |
| `last_successful_run_id`        | STRING    | Airflow `run_id`                       |
| `updated_at`                    | TIMESTAMP |                                        |

#### meta.run_metrics

Created on demand by Airflow before write operations if the table does not already exist.

| Column              | Type      | Notes                         |
|---------------------|-----------|-------------------------------|
| `run_id`            | STRING    | Airflow `run_id`              |
| `dag_id`            | STRING    |                               |
| `execution_date`    | TIMESTAMP |                               |
| `window_start`      | TIMESTAMP |                               |
| `window_end`        | TIMESTAMP |                               |
| `rows_loaded`       | INT64     |                               |
| `dbt_models_passed` | INT64     |                               |
| `dbt_tests_passed`  | INT64     |                               |
| `dbt_tests_failed`  | INT64     |                               |
| `bytes_processed`   | INT64     |                               |
| `duration_seconds`  | FLOAT64   |                               |
| `status`            | STRING    | `"success"` | `"failed"`     |
| `created_at`        | TIMESTAMP |                               |

#### meta.freshness_log

Created on demand by Airflow before write operations if the table does not already exist.

| Column                          | Type      | Notes                              |
|---------------------------------|-----------|------------------------------------|
| `run_id`                        | STRING    | Airflow `run_id`                   |
| `pipeline_freshness_timestamp`  | TIMESTAMP | `MAX(_ingestion_timestamp)` from raw |
| `data_freshness_timestamp`      | TIMESTAMP | `MAX(observation_timestamp)` from staging |
| `pipeline_freshness_status`     | STRING    | `"fresh"` | `"stale"`             |
| `data_freshness_status`         | STRING    | `"fresh"` if `checked_at - data_freshness_timestamp <= 6 hours`, otherwise `"stale"` |
| `checked_at`                    | TIMESTAMP |                                    |

#### meta.anomaly_results

Created on demand by Airflow before write operations if the table does not already exist.

| Column            | Type      | Notes                              |
|-------------------|-----------|------------------------------------|
| `observation_date`| DATE      |                                    |
| `region`          | STRING    |                                    |
| `metric_name`     | STRING    |                                    |
| `current_value`   | FLOAT64   |                                    |
| `rolling_7d_avg`  | FLOAT64   | Average over the prior 7 calendar days for the same `region` and `metric_name`, excluding the current date |
| `pct_deviation`   | FLOAT64   | `NULL` when `rolling_7d_avg` is `NULL` or `0` |
| `anomaly_flag`    | BOOLEAN   | True if `|pct_deviation| > 50%`; `FALSE` when the rolling baseline is unavailable or zero |
| `run_id`          | STRING    | Airflow `run_id`                   |
| `checked_at`      | TIMESTAMP |                                    |

---

## 3. GCS Path Convention

```
gs://<bucket>/voltage-hub/raw/year=YYYY/month=MM/day=DD/window=<start_iso>/batch.json
```

Components:
- `<bucket>` — from `GCS_BUCKET_NAME` env var
- `year`, `month`, `day` — derived from extraction window start
- `<start_iso>` — ISO 8601 timestamp of `data_interval_start`

---

## 4. Configuration Schema

### Required Environment Variables (.env)

| Variable                          | Description                                | Default          |
|-----------------------------------|--------------------------------------------|------------------|
| `GCP_PROJECT_ID`                  | GCP project ID                             | (required)       |
| `GCP_REGION`                      | GCP region                                 | `us-central1`    |
| `GCP_SERVICE_ACCOUNT_KEY_PATH`    | Path to service account JSON key           | (required)       |
| `GCS_BUCKET_NAME`                 | GCS bucket for raw landing                 | (required)       |
| `BQ_DATASET_RAW`                  | BigQuery raw dataset name                  | `raw`            |
| `BQ_DATASET_STAGING`              | BigQuery staging dataset name              | `staging`        |
| `BQ_DATASET_MARTS`                | BigQuery marts dataset name                | `marts`          |
| `BQ_DATASET_META`                 | BigQuery meta dataset name                 | `meta`           |
| `BQ_DATASET_RAW_SAMPLE`           | BigQuery raw dataset name for sample mode  | `raw_sample`     |
| `BQ_DATASET_STAGING_SAMPLE`       | BigQuery staging dataset name for sample mode | `staging_sample` |
| `BQ_DATASET_MARTS_SAMPLE`         | BigQuery marts dataset name for sample mode | `marts_sample`   |
| `BQ_DATASET_META_SAMPLE`          | BigQuery meta dataset name for sample mode | `meta_sample`    |
| `AIRFLOW__CORE__EXECUTOR`         | Airflow executor                           | `LocalExecutor`  |
| `AIRFLOW__DATABASE__SQL_ALCHEMY_CONN` | Airflow metadata DB connection         | (required)       |
| `BACKFILL_DAYS`                   | Default backfill window in days            | `7`              |
| `SAMPLE_MODE`                     | Enables sample-mode routing to the isolated sample BigQuery datasets | `false` |
| `DBT_RUN_RESULTS_PATH`            | Path to dbt `run_results.json` artifact used for run metrics | `/opt/airflow/dbt/target/run_results.json` |
| `EIA_API_KEY`                     | EIA API key                                | (required)       |
| `GOOGLE_APPLICATION_CREDENTIALS`  | Path to service account key (for serving)  | (required)       |
| `PORT`                            | Serving API port                           | `8090`           |
| `CACHE_TTL_SECONDS`               | Serving API in-memory aggregate cache TTL in seconds | `300` |

### Optional Integration-Test Environment Variables

| Variable                               | Description | Default |
|----------------------------------------|-------------|---------|
| `VOLTAGE_HUB_RUN_PIPELINE_TESTS`       | Enables real Airflow/GCS/BigQuery integration tests in `tests/integration/test_pipeline_e2e.py` | unset / disabled |
| `VOLTAGE_HUB_RUN_HEAVY_PIPELINE_TESTS` | Enables the slower idempotent-rerun and backfill integration cases | unset / disabled |
| `VOLTAGE_HUB_TEST_BACKFILL_HOURS`      | Optional heavy-test backfill depth, measured in hourly windows | `2` |
| `VOLTAGE_HUB_TEST_BACKFILL_END_BOUNDARY` | Optional heavy-test backfill exclusive upper boundary; the harness backfills the preceding hourly windows ending at this hour-aligned timestamp | `2026-03-27T00:00:00+00:00` |
| `VOLTAGE_HUB_TEST_EXECUTION_DATE`      | Airflow logical execution timestamp passed to `airflow dags test`; for the hourly DAG this aligns to `data_interval_end` | `2026-03-27T01:00:00+00:00` |
| `VOLTAGE_HUB_TEST_WINDOW_START`        | Optional explicit override for the expected extraction window start used by the test harness | derived as `VOLTAGE_HUB_TEST_WINDOW_END - 1 hour` |
| `VOLTAGE_HUB_TEST_WINDOW_END`          | Optional explicit override for the expected extraction window end used by the test harness | `VOLTAGE_HUB_TEST_EXECUTION_DATE` |

---

## 5. dbt Source Definition Contract

```yaml
sources:
  - name: raw
    database: "{{ env_var('GCP_PROJECT_ID') }}"
    schema: "{{ env_var('BQ_DATASET_RAW_SAMPLE', 'raw_sample') if target.name == 'sample' else env_var('BQ_DATASET_RAW', 'raw') }}"
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

---

## 6. Response Contract — REST Data Endpoint Metadata

Every data endpoint (load metrics, generation mix, top regions) wraps its response with:

```
{
  "data": [ ... ],
  "metadata": {
    "data_as_of": "<ISO timestamp>",
    "pipeline_run_id": "<string>",
    "freshness_status": "fresh" | "stale" | "unknown"
  }
}
```

- `data_as_of` — latest `data_freshness_timestamp` from `meta.freshness_log`
- `pipeline_run_id` — from `meta.pipeline_state.last_successful_run_id`
- `freshness_status` — derived from worse of `pipeline_freshness_status` and `data_freshness_status`
