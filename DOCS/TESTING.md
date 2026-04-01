# TESTING.md — VoltageHub

---

## 1. Testing Philosophy

This project has three distinct runtime systems — infrastructure provisioning, a batch ELT pipeline, and a serving layer — each with different failure modes. Testing must cover:

- **Infrastructure correctness** — cloud resources exist and are configured properly
- **Pipeline reliability** — data flows end-to-end, partitions rebuild idempotently, quality gates enforce invariants
- **Warehouse model correctness** — dbt transformations produce expected outputs, tests enforce schema contracts
- **Serving interface contract compliance** — REST endpoints and MCP tools/resources return valid responses with correct metadata against real warehouse data

Testing is not bolted on at the end. dbt tests run inside the pipeline (`dbt build`). Freshness and anomaly checks are first-class pipeline tasks. Serving validation runs against populated BigQuery tables, with MCP testing intentionally scoped to tool/resource behavior rather than end-to-end agent evaluation.

---

## 2. Test Layers

### 2.1 Infrastructure Validation

**What:** Terraform provisions the correct GCP resources.

| Test                                      | Method                                 | Pass Criteria                                                |
|-------------------------------------------|----------------------------------------|--------------------------------------------------------------|
| `terraform plan` succeeds                 | CLI                                    | No errors; expected resource diff                            |
| `terraform apply` provisions resources    | CLI + GCP console                      | GCS bucket exists; BQ datasets (`raw`, `staging`, `marts`, `meta`) exist; service account exists with correct roles |
| `terraform destroy` cleans up             | CLI + GCP console                      | All resources removed                                        |
| Docker Compose starts                     | `docker compose up -d`                 | All containers healthy; Airflow UI at `localhost:8080`        |
| dbt available in container                | `dbt deps` inside container            | Exits 0                                                      |

### 2.2 Unit Tests — Extraction and Loading

**What:** Individual Python functions behave correctly in isolation.

| Component                     | What to Test                                                       | Approach                            |
|-------------------------------|--------------------------------------------------------------------|-------------------------------------|
| `extract_grid_batch`          | API call construction, time window parameter formatting            | Mock `requests` responses           |
| `extract_grid_batch` retries  | 429 → backoff, 5xx → retry, timeout → retry, malformed → fail     | Mock HTTP error responses           |
| `land_raw_to_gcs`             | Correct GCS path generation, upload call                           | Mock GCS client                     |
| `load_to_bq_raw`              | Correct load job config: schema, partition, `WRITE_TRUNCATE`       | Mock BigQuery client                |
| Response validation           | Empty response rejected; valid response accepted                   | Unit test with sample payloads      |

**Mocks appropriate here:** GCS and BigQuery clients. Do not call real APIs in unit tests.

### 2.3 dbt Tests (Run Inside Pipeline)

**What:** Data quality invariants enforced at every build.

These run automatically as part of `dbt build`. They are not separate from the pipeline — they are the pipeline's quality gates.

**Required tests (from SPEC Section 12.1):**

| Table                 | Test                                                  | Type              |
|-----------------------|-------------------------------------------------------|-------------------|
| `stg_grid_metrics`    | `not_null` on `metric_surrogate_key`, `observation_timestamp`, `region`, `metric_name` | Column test       |
| `stg_grid_metrics`    | `unique` on `metric_surrogate_key`                    | Column test       |
| `stg_grid_metrics`    | `not_null` on `metric_value`                          | Column test       |
| `stg_grid_metrics`    | `accepted_values` on `metric_name`                    | Column test       |
| `stg_grid_metrics`    | `accepted_values` on `energy_source` using the documented Voltage Hub fuel-code set (`BAT`, `BIO`, `COL`, `GEO`, `HPS`, `HYC`, `NG`, `NUC`, `OES`, `OIL`, `OTH`, `PS`, `SNB`, `SUN`, `UES`, `UNK`, `WAT`, `WNB`, `WND`) | Column test       |
| `fct_grid_metrics`    | `relationships` to `dim_region.region`                | Relationship test |
| `fct_grid_metrics`    | `relationships` to `dim_energy_source.energy_source`  | Relationship test |
| `fct_grid_metrics`    | Grain uniqueness: `(region, observation_timestamp, metric_name, energy_source)` | Custom/unique test |

**Failure behavior:** Any dbt test failure **fails** the DAG run.

### 2.4 Freshness Tests (Run Inside Pipeline)

| Check                        | Trigger                                              | Behavior         |
|------------------------------|------------------------------------------------------|------------------|
| Pipeline freshness `warn`    | `_ingestion_timestamp` > 6 hours stale               | Warning only     |
| Pipeline freshness `error`   | `_ingestion_timestamp` > 12 hours stale              | **Fails** DAG    |
| Data freshness               | `observation_timestamp` stale (post-build check)     | Logged to `meta.freshness_log` |

**Additional required execution flows:**
- **Freshness warn-path validation:** run `dbt source freshness` against an isolated test raw dataset whose latest `_ingestion_timestamp` is older than 6 hours but not older than 12 hours. Verify the command surfaces a warning without failing and that the isolated test datasets are deleted after the check completes.
- **Freshness error-path validation:** run `dbt source freshness` against an isolated test raw dataset whose latest `_ingestion_timestamp` is older than 12 hours. Verify the command fails before `dbt build` would proceed and that the isolated test datasets are deleted after the check completes.
- **Two-signal freshness validation:** validate all four combinations for the consumer-facing freshness signals where feasible: both fresh, pipeline stale + data fresh, pipeline fresh + data stale, and missing freshness data producing `unknown`.
- **Failure-path run-metrics validation:** intentionally trigger a real pipeline failure after `record_run_metrics` is scheduled to run with `TriggerRule.ALL_DONE` (for example through a `dbt source freshness` failure or `dbt build` failure). Verify `meta.run_metrics` still receives a row with `status = "failed"` and that `meta.freshness_log` either records the observed values or the documented `unknown` fallback.

### 2.5 Integration Tests — End-to-End Pipeline

**What:** Full pipeline run produces correct outputs.

**Airflow timing note:** `airflow dags test <dag_id> <timestamp>` takes the DAG run logical execution timestamp. For the default hourly schedule, that timestamp aligns to `data_interval_end`, so the actual extraction window start is one schedule interval earlier unless explicitly overridden in the test harness.

| Test                                          | Method                                          | Pass Criteria                                                     |
|-----------------------------------------------|-------------------------------------------------|-------------------------------------------------------------------|
| Single window extraction + load               | Trigger DAG manually for one time window        | Raw data in GCS at correct path; rows in `raw.eia_grid_batch`     |
| dbt build after load                          | Part of DAG run                                 | 0 test failures; staging + marts populated                        |
| Aggregate tables populated                    | Query `agg_*` tables                            | Rows present for expected periods                                 |
| Meta tables populated                         | Query `meta.*` tables                            | `pipeline_state` watermark updated; `run_metrics` row created; `freshness_log` entry exists |
| Anomaly results recorded                      | Query `meta.anomaly_results`                    | Rows present (flag values may vary)                               |
| Idempotent rerun                              | Re-trigger same window                           | Same output; no duplicate rows; same partition content            |
| Date-boundary window rebuild                  | Trigger a window that spans midnight UTC and query staging/marts partitions | Affected `observation_date` set contains 2 dates; both date partitions are rebuilt correctly |
| Backfill                                      | `airflow dags backfill` for 2+ windows           | Each window processed sequentially; all outputs correct           |

**Real data required here:** Integration tests must run against actual GCP resources with real EIA API responses (or pre-captured snapshots loaded from GCS).

**Recommended execution split:**
- **Smoke path:** run the single-window and meta-output integration tests on every meaningful pipeline change
- **Heavy path:** run idempotent rerun and backfill validation separately because they intentionally re-run the pipeline and take materially longer
- The current integration suite uses `VOLTAGE_HUB_RUN_PIPELINE_TESTS=1` to enable real-resource tests and `VOLTAGE_HUB_RUN_HEAVY_PIPELINE_TESTS=1` to opt into the slower rerun/backfill cases
- Heavy backfill validation anchors its expected windows on Airflow backfill logical dates (`window_start` semantics). By default it backfills the `VOLTAGE_HUB_TEST_BACKFILL_HOURS` windows immediately preceding `VOLTAGE_HUB_TEST_BACKFILL_END_BOUNDARY=2026-03-27T00:00:00+00:00`
- **Separate failure-path path:** run freshness-threshold and forced-failure validation independently from smoke and heavy coverage because they intentionally create stale or failing conditions in isolated temporary datasets and are best treated as targeted operational checks rather than every-change regression tests

### 2.6 Serving REST API Tests

| Test                                          | Method                                          | Pass Criteria                                                     |
|-----------------------------------------------|-------------------------------------------------|-------------------------------------------------------------------|
| `GET /health`                                 | HTTP request                                    | 200 response, no BigQuery dependency                              |
| `GET /freshness`                              | HTTP request                                    | Returns `pipeline_freshness_timestamp`, `data_freshness_timestamp`, `freshness_status` |
| `GET /pipeline/status`                        | HTTP request                                    | Returns latest window, `last_successful_run_id`                   |
| `GET /anomalies`                              | HTTP request                                    | Returns anomaly summary from `meta.anomaly_results`               |
| Load metrics endpoint                         | HTTP request with region, time range, granularity | Returns data from `agg_load_hourly` or `agg_load_daily`          |
| Generation mix endpoint                       | HTTP request with region, time range             | Returns data from `agg_generation_mix`                            |
| Top regions endpoint                          | HTTP request with date range, limit              | Returns per-day ranked data from `agg_top_regions`; `limit` applies per `observation_date` |
| Response metadata                             | All data endpoints                               | Every response contains `data_as_of`, `pipeline_run_id`, `freshness_status` |
| Invalid parameters                            | HTTP request with bad inputs                     | Structured error response with validation details                 |
| Cache behavior (if enabled)                   | Repeated requests within TTL                     | Second request served from cache (faster response, same data)     |

**Approach:** Integration-level tests against a running FastAPI instance with populated BigQuery tables. Mock BigQuery client for unit-level service/repository tests.

### 2.7 MCP Tool and Resource Tests

| Test                                          | Method                                          | Pass Criteria                                                     |
|-----------------------------------------------|-------------------------------------------------|-------------------------------------------------------------------|
| MCP server startup                            | Launch MCP process over `stdio` via `uv run voltagehub-mcp` or host-equivalent `uvx voltagehub-mcp` | Process starts cleanly and exposes expected registration          |
| Tool discovery                                | MCP tool list/query                             | All 6 documented tools are registered                            |
| Resource discovery                            | MCP resource list/query                         | All 4 documented resources are registered                        |
| Tool success envelope                         | MCP tool invocation                             | Response contains `summary`, `highlights`, `data`, `metadata`    |
| Tool error envelope                           | MCP tool invocation with bad inputs             | Structured MCP error category is returned                        |
| Resource payload structure                    | MCP resource read                               | Payload shape matches documented v1 guarantees                   |
| Mapping correctness                           | Compare MCP tool semantics to shared serving capability | Tool behavior matches the corresponding REST/service semantics |
| Region normalization                          | MCP tool invocation with canonical `region` and exact `region_name` | Deterministic normalization succeeds; aliases are not required |
| Empty-result behavior                         | Valid MCP query with no matching rows           | Success envelope with empty `data` and deterministic summary     |
| Time-semantics behavior                       | MCP date-filtered calls                         | Inclusive `observation_date` filtering behaves as documented     |
| Oversize / validation-first behavior          | Wide MCP queries                                | Validation-first tools reject oversize requests deterministically |
| Truncation behavior                           | Large anomaly query without date filters        | Truncation is explicit in metadata when applied                  |

**Approach:** MCP-focused tests should stop at tool/resource behavior. They should validate startup, discovery, contracts, normalization, and overflow behavior without adding agent usability tests or remote transport tests. Prefer local dev verification through `uv run voltagehub-mcp`, and treat `uvx voltagehub-mcp` as the equivalent packaged-host startup shape.

Out of scope:
- automated end-to-end prompt-loop evaluation
- agent usability tests
- HTTP, SSE, or other remote transport testing

### 2.8 CI Validation

| Test                          | Method                              | Pass Criteria            |
|-------------------------------|-------------------------------------|--------------------------|
| SQL lint                      | `sqlfluff lint`                     | No errors                |
| Python lint                   | `ruff check`                        | No errors                |
| dbt project parse             | `dbt deps && dbt parse --target ci --no-populate-cache` | Exits 0 |
| Terraform validate            | `terraform fmt -check && terraform validate` | Exits 0         |

CI does **not** connect to GCP. Syntax and quality checks only.

---

## 3. Highest-Risk Areas (Test First)

Prioritized by blast radius and likelihood of failure:

1. **EIA API extraction** — external dependency, rate limits, schema changes, empty responses. Test retry logic and response validation thoroughly.
2. **Partition rebuild logic** — `insert_overwrite` scoped to affected `observation_date` set. Incorrect scoping causes data loss or stale partitions. Test with windows spanning date boundaries.
3. **Staging canonicalization** — type casting, field mapping, surrogate key generation. Bad mapping corrupts all downstream tables. Test with varied raw payloads.
4. **Idempotent rerun** — re-running a window must produce identical output. Test explicitly by running same window twice and diffing results.
5. **Freshness two-signal logic** — combined status derivation (worst of pipeline + data). Test edge cases: one fresh + one stale, both stale, both fresh, missing data.
6. **Serving interface response contracts** — REST metadata fields and MCP response envelopes must remain stable. Test separately from data correctness.
7. **MCP normalization and overflow behavior** — region normalization, validation-first limits, and explicit truncation rules are easy to drift. Test these directly.

---

## 4. Critical Edge Cases

| Scenario                                  | Expected Behavior                                              |
|-------------------------------------------|----------------------------------------------------------------|
| EIA API returns empty data for a window   | Task fails with clear error message                            |
| EIA API returns unexpected schema         | Response validation rejects; task fails                        |
| Extraction window spans date boundary     | Affected date set contains 2 dates; both partitions rebuilt    |
| Raw table has no data for expected batch  | dbt source freshness triggers warn/error                       |
| Rerun of previously completed window      | Idempotent: same output, no duplicates                         |
| Concurrent DAG runs                       | Prevented by `max_active_runs=1`                               |
| BigQuery load job fails                   | Airflow task retries (2x, 5-min delay)                         |
| dbt test failure                          | DAG run fails; downstream tasks do not execute                 |
| Anomaly threshold exceeded                | Warning flagged; DAG continues successfully                    |
| Freshness warn threshold exceeded         | Warning emitted against the isolated failure-path raw dataset; shared development datasets remain unchanged |
| Freshness error threshold exceeded        | `dbt source freshness` fails against the isolated failure-path raw dataset; shared development datasets remain unchanged |
| Run fails after control-plane tasks are eligible | `meta.run_metrics.status` records `failed` and freshness logging follows documented fallback behavior |
| Meta tables missing/empty                 | Serving API endpoints return appropriate error or empty state  |
| Serving API called before any pipeline run | Freshness/status endpoints handle gracefully (empty/unknown)  |
| MCP `get_load_trends(hourly)` over more than 7 days | Returns `validation_error`; request is not auto-shortened |
| Valid MCP query returns no matching rows  | Returns success envelope with empty `data` and deterministic summary |
| MCP freshness query with no freshness rows | Returns deterministic payload with `freshness_status = "unknown"` |

---

## 5. Fixture and Sample Data

- **Raw API response fixture:** Capture a real EIA API response for a known time window. Store in `tests/fixtures/` (or equivalent). Use for unit testing extraction parsing and staging transformations.
- **Sample mode:** `SAMPLE_MODE=true` extracts minimal window into separate dataset for quick validation without impacting production data.
- **GCS replay:** Previously landed raw files in GCS can be re-loaded without calling the EIA API. Useful for reproducible integration testing.

---

## 6. Anti-Patterns to Avoid

- **Do not test dbt models with mock data outside dbt.** Use dbt's own test framework against real warehouse tables. dbt tests are part of the pipeline, not a separate test suite.
- **Do not mock BigQuery for integration tests.** Integration tests must verify real query execution against actual datasets.
- **Do not test aggregate correctness through the serving API alone.** Validate aggregate tables directly in BigQuery first; then verify the serving API returns the same data.
- **Do not treat MCP as an agent-evaluation surface in v1.** Test tools/resources directly; do not expand this phase into agent usability or prompt-loop testing.
- **Do not skip idempotency testing.** Idempotent rerun is a core design guarantee. Test it explicitly.
- **Do not treat anomaly detection as pass/fail.** It is warning-only. Tests should verify results are recorded, not that specific anomalies are flagged.
- **Do not test CI workflows by connecting to GCP.** CI validates syntax only.

---

## 7. Milestone Completion Criteria

### Phase 1 Complete When:
- `terraform apply` + `terraform destroy` clean cycle
- Docker Compose starts; Airflow UI healthy
- Single DAG run: extract → GCS → BigQuery raw → dbt staging → marts → aggregates
- `dbt build` passes with 0 test failures
- Rerun of same window produces identical output

### Phase 2 Complete When:
- `meta.pipeline_state`, `meta.run_metrics`, `meta.freshness_log`, `meta.anomaly_results` all populated after a run
- `dbt source freshness` runs without error
- Freshness log contains both pipeline and data freshness signals
- Anomaly results table populated (warning-only, DAG succeeds)

### Phase 3 Complete When:
- All serving API endpoints respond with valid, schema-conformant responses
- Health endpoint returns 200 independently of BigQuery
- Data endpoints include `data_as_of`, `pipeline_run_id`, `freshness_status`
- Invalid parameters return structured errors
- MCP server starts in `stdio` mode and exposes the documented tools/resources
- MCP tool/resource tests pass for registration, envelopes, normalization, and overflow behavior
- `unsupported_capability` remains documented for contract stability, but v1 tests do not require a dedicated parameter-level trigger for it
- No agent usability testing is required for MCP v1

### Phase 4 Complete When:
- All CI workflows pass on a clean PR
- README with setup and usage instructions exists
- dbt docs generated
- All models and columns have descriptions in `schema.yml`
