## [2026-03-28 Round 35]

### Completed
- Completed `Task 3.6` for serving-layer exception handling, structured error responses, and request logging middleware
- Prepared `Task 3.7` runtime surfaces by making the serving container honor `PORT`, but did not execute verification commands in this round

### Files Added/Modified
- `serving-fastapi/app/exceptions/base.py`
- `serving-fastapi/app/exceptions/handlers.py`
- `serving-fastapi/app/middleware/__init__.py`
- `serving-fastapi/app/middleware/request_logging.py`
- `serving-fastapi/app/main.py`
- `serving-fastapi/Dockerfile`
- `DOCS/TASKS.md`
- `CHANGELOG.md`

### Interface or Behavior Changes
- FastAPI request-validation failures now return structured JSON responses instead of the default FastAPI validation payload
- Added request-level logging middleware that records method, path, query string, status code, request duration, client address, and an `x-request-id`
- The serving container now starts `uvicorn` using `PORT` from the environment, defaulting to `8090`

### Tests Added/Passed
- Not run in this round per request; this round was limited to implementation work and did not execute serving verification commands

### Known Issues
- `Task 3.7` verification steps remain marked in progress because the requested no-testing workflow means the startup, endpoint, and Docker verification commands were not executed
- Structured validation errors currently return a compact stringified detail payload; if a field-by-field error schema is later required, update the response contract and handlers together

## [2026-03-28 Round 34]

### Completed
- Completed `Task 3.5` by adding in-memory TTL caching for hot aggregate serving queries

### Files Added/Modified
- `serving-fastapi/app/cache/query_cache.py`
- `serving-fastapi/app/cache/__init__.py`
- `serving-fastapi/app/config/settings.py`
- `serving-fastapi/app/services/metrics.py`
- `.env.example`
- `DOCS/INTERFACES.md`
- `DOCS/ARCHITECTURE.md`
- `DOCS/TASKS.md`
- `CHANGELOG.md`

### Interface or Behavior Changes
- Added serving-layer `CACHE_TTL_SECONDS` configuration with a default of `300`
- Metric endpoints now cache hot aggregate query results in memory using `cachetools.TTLCache`
- Cache keys are derived from the endpoint identity plus request parameters; response metadata continues to be built from the latest `meta.*` lookups instead of the cached aggregate rows

### Tests Added/Passed
- Not run in this round per request; this round was limited to development work for `Task 3.5`

### Known Issues
- `Task 3.6+` remains unimplemented; custom exception expansion, request logging middleware, and full runtime verification are still pending
- The in-memory cache is process-local by design and is cleared on restart, which matches the current single-service, no-external-cache architecture

## [2026-03-28 Round 36]

### Completed
- Completed the offline CI expansion for Phase 3 by wiring the serving FastAPI unit test suite into GitHub Actions without adding any real GCP dependency
- Completed `Task 4.1` verification update in `DOCS/TASKS.md` now that Phase 3 serving-layer tests are included in CI coverage

### Files Added/Modified
- `.github/workflows/lint.yml`
- `DOCS/TASKS.md`
- `CHANGELOG.md`

### Interface or Behavior Changes
- No API, warehouse, or runtime behavior changes
- `lint.yml` now installs the serving API's locked dependencies in `serving-fastapi/` and runs the offline serving unit suite separately from the root project unit tests

### Tests Added/Passed
- Passed: `uv run ruff check .`
- Passed: `uv run pytest -q tests/unit/test_eia_grid_batch_tasks.py tests/unit/test_dbt_testing_contracts.py` (`18 passed`)
- Passed: `uv run sqlfluff lint --config .sqlfluff.ci dbt/models`
- Passed: `cd serving-fastapi && UV_CACHE_DIR=/tmp/uv-cache uv sync --dev --frozen`
- Passed: `cd serving-fastapi && uv run pytest -q ../tests/unit/serving_fastapi` (`23 passed`)

### Known Issues
- The CI expansion remains intentionally offline; real-resource serving integration tests stay out of standard GitHub Actions coverage for this personal-project setup

## [2026-03-28 Round 35]

### Completed
- Executed the full Phase 3 serving-layer test suite against the current real cloud datasets and confirmed the opt-in integration coverage passes with populated `marts` and `meta` tables

### Files Added/Modified
- `CHANGELOG.md`

### Interface or Behavior Changes
- No API, schema, config, or runtime behavior changes
- This round records successful real-resource validation of the existing Phase 3 serving implementation

### Tests Added/Passed
- Passed: `set -a; source .env; set +a; cd serving-fastapi && UV_CACHE_DIR=/tmp/uv-cache VOLTAGE_HUB_RUN_PIPELINE_TESTS=1 uv run pytest ../tests/unit/serving_fastapi ../tests/integration/test_serving_api.py -q` (`29 passed`)

### Known Issues
- No serving-layer failures were observed in this validation run

## [2026-03-28 Round 34]

### Completed
- Completed the remaining serving-layer test flows from `TESTING.md Section 2.6` for invalid-parameter handling, request metadata headers, cache behavior, and real-resource-ready serving integration coverage
- Added an opt-in serving API integration suite that validates control-plane and metric endpoints against populated BigQuery tables when real test mode is enabled

### Files Added/Modified
- `tests/unit/serving_fastapi/test_control_plane.py`
- `tests/unit/serving_fastapi/test_metrics.py`
- `tests/integration/test_serving_api.py`
- `CHANGELOG.md`

### Interface or Behavior Changes
- No API contract or runtime behavior changes
- Added serving test coverage for structured `validation_error` responses, `x-request-id` propagation, repeated-request cache hits within TTL, and env-gated integration validation against real `marts` / `meta` datasets

### Tests Added/Passed
- Passed: `uv run ruff check tests/unit/serving_fastapi/test_control_plane.py tests/unit/serving_fastapi/test_metrics.py`
- Passed: `uv run ruff check tests/integration/test_serving_api.py`
- Passed: `cd serving-fastapi && uv run pytest ../tests/unit/serving_fastapi -q` (`23 passed`)
- Passed: `cd serving-fastapi && uv run pytest ../tests/integration/test_serving_api.py -q` (`6 skipped` without `VOLTAGE_HUB_RUN_PIPELINE_TESTS=1`)
- Passed: `cd serving-fastapi && uv run pytest ../tests/unit/serving_fastapi ../tests/integration/test_serving_api.py -q` (`23 passed, 6 skipped`)
- Passed: `uv run python -m compileall tests/unit/serving_fastapi tests/integration/test_serving_api.py`

### Known Issues
- The new serving integration suite is intentionally opt-in and was not executed against real BigQuery tables in this round because `VOLTAGE_HUB_RUN_PIPELINE_TESTS=1` was not enabled in the current environment

## [2026-03-28 Round 33]

### Completed
- Completed additional `TESTING.md Section 2.6` coverage for the three metric data endpoints: load metrics, generation mix, and top regions
- Completed explicit response metadata coverage for `data_as_of`, `pipeline_run_id`, and `freshness_status` on all three metric endpoint responses

### Files Added/Modified
- `tests/unit/serving_fastapi/test_metrics.py`
- `CHANGELOG.md`

### Interface or Behavior Changes
- No API contract or runtime behavior changes
- Strengthened serving-layer tests to assert metric response envelopes and metadata fallback behavior without modifying endpoint implementation

### Tests Added/Passed
- Passed: `uv run ruff check tests/unit/serving_fastapi/test_metrics.py`
- Passed: `cd serving-fastapi && uv run pytest ../tests/unit/serving_fastapi/test_metrics.py -q` (`6 passed`)

### Known Issues
- These additions remain unit/interface-level tests with dependency overrides; `TESTING.md Section 2.6` integration coverage against a running FastAPI instance backed by populated real BigQuery tables is still pending

## [2026-03-28 Round 32]

### Completed
- Completed `TESTING.md Section 2.6` coverage for `GET /health`, `GET /freshness`, `GET /pipeline/status`, and `GET /anomalies`

### Files Added/Modified
- `tests/unit/serving_fastapi/test_control_plane.py`
- `CHANGELOG.md`

### Interface or Behavior Changes
- No API contract or runtime behavior changes
- Added control-plane endpoint test coverage for empty-state and default-filter behavior without modifying serving implementation

### Tests Added/Passed
- Passed: `uv run ruff check tests/unit/serving_fastapi/test_control_plane.py`
- Passed: `cd serving-fastapi && uv run pytest ../tests/unit/serving_fastapi/test_control_plane.py -q` (`9 passed`)

### Known Issues
- `TESTING.md Section 2.6` cases for metric endpoints, response metadata on data endpoints, invalid-parameter handling, and cache behavior remain pending because the corresponding serving-layer work is not in scope yet

## [2026-03-28 Round 32]

### Completed
- Completed `Task 3.4` for the FastAPI metric endpoints backed by `marts.agg_*` plus shared response metadata from `meta.freshness_log` and `meta.pipeline_state`

### Files Added/Modified
- `serving-fastapi/app/repositories/metrics.py`
- `serving-fastapi/app/services/metrics.py`
- `serving-fastapi/app/routers/metrics.py`
- `serving-fastapi/app/schemas/metrics.py`
- `serving-fastapi/app/main.py`
- `tests/unit/serving_fastapi/test_metrics.py`
- `tests/unit/serving_fastapi/test_control_plane.py`
- `DOCS/TASKS.md`
- `CHANGELOG.md`

### Interface or Behavior Changes
- Added `GET /metrics/load`, `GET /metrics/generation-mix`, and `GET /metrics/top-regions`
- Metric endpoints query only `marts.agg_load_hourly`, `marts.agg_load_daily`, `marts.agg_generation_mix`, and `marts.agg_top_regions` with parameterized `WHERE` filters and per-day `rank <= limit` filtering for top regions
- All metric responses now return the documented envelope with `data_as_of`, `pipeline_run_id`, and combined `freshness_status`

### Tests Added/Passed
- Passed: `uv run ruff check serving-fastapi tests/unit/serving_fastapi`
- Passed: `uv run python -m compileall serving-fastapi/app tests/unit/serving_fastapi`
- Passed: `cd serving-fastapi && uv run pytest ../tests/unit/serving_fastapi -q` (`15 passed`)
- Passed: `cd serving-fastapi && uv run python -c "from app.main import app; print(sorted(route.path for route in app.routes if hasattr(route, 'path')))"` (verified metric routes are registered)

### Known Issues
- `Task 3.5+` remains intentionally unimplemented in this round; TTL caching, request logging middleware, and full BigQuery-backed runtime verification are still pending
- `GET /metrics/load` validates `granularity` through the FastAPI/Pydantic enum surface and rejects unsupported values before repository execution

## [2026-03-28 Round 31]

### Completed
- Completed `Task 3.1`, `Task 3.2`, and `Task 3.3` for the FastAPI serving layer scaffold, config/repository setup, and control-plane endpoints

### Files Added/Modified
- `serving-fastapi/pyproject.toml`
- `serving-fastapi/Dockerfile`
- `serving-fastapi/app/main.py`
- `serving-fastapi/app/config/settings.py`
- `serving-fastapi/app/config/bigquery.py`
- `serving-fastapi/app/repositories/base.py`
- `serving-fastapi/app/repositories/control_plane.py`
- `serving-fastapi/app/services/control_plane.py`
- `serving-fastapi/app/routers/health.py`
- `serving-fastapi/app/routers/control_plane.py`
- `serving-fastapi/app/schemas/common.py`
- `serving-fastapi/app/schemas/health.py`
- `serving-fastapi/app/schemas/control_plane.py`
- `serving-fastapi/app/schemas/error.py`
- `serving-fastapi/app/health/service.py`
- `serving-fastapi/app/exceptions/base.py`
- `serving-fastapi/app/exceptions/handlers.py`
- `tests/unit/serving_fastapi/test_control_plane.py`
- `tests/unit/serving_fastapi/test_settings.py`
- `DOCS/TASKS.md`
- `CHANGELOG.md`

### Interface or Behavior Changes
- Added the standalone `serving-fastapi/` application scaffold defined in `SPEC.md`, including the canonical `app.main:app` entrypoint
- Added environment-backed serving settings for `GCP_PROJECT_ID`, `BQ_DATASET_MARTS`, `BQ_DATASET_META`, `PORT`, and `GOOGLE_APPLICATION_CREDENTIALS`
- Added read-only control-plane endpoints for `/health`, `/freshness`, `/pipeline/status`, and `/anomalies`
- `/freshness` now derives the consumer-facing combined `freshness_status` from the worse of `pipeline_freshness_status` and `data_freshness_status`

### Tests Added/Passed
- Passed: `uv run python -m compileall serving-fastapi tests/unit/serving_fastapi`
- Passed: `uv run ruff check serving-fastapi tests/unit/serving_fastapi`
- Passed: `cd serving-fastapi && UV_CACHE_DIR=/tmp/uv-cache uv sync --dev`
- Passed: `cd serving-fastapi && uv run pytest ../tests/unit/serving_fastapi -q` (`7 passed`)
- Passed: `cd serving-fastapi && uv run python -c "from app.main import app; print(app.title)"`

### Known Issues
- `Task 3.4+` remains intentionally unimplemented in this round; metric endpoints, caching, request logging, and Docker/runtime verification against populated BigQuery tables are still pending
- `GET /anomalies` currently returns the list of anomaly records directly; if a future response envelope is required, update `INTERFACES.md` and the endpoint schema together

## [2026-03-28 Round 30]

### Completed
- Replaced the failing CI `dbt compile` step with offline `dbt parse --no-populate-cache` validation for the BigQuery-backed dbt project
- Updated the project documentation so CI now accurately states the non-GCP dbt validation path instead of claiming warehouse-touching `compile` behavior is offline-safe

### Files Added/Modified
- `.github/workflows/dbt_compile.yml`
- `DOCS/SPEC.md`
- `DOCS/ARCHITECTURE.md`
- `DOCS/TESTING.md`
- `DOCS/TASKS.md`
- `CHANGELOG.md`

### Interface or Behavior Changes
- No API, warehouse, DAG, or real-environment behavior changes
- CI dbt validation now uses offline parsing instead of compile because the BigQuery adapter may populate relation caches during `dbt compile`, which violates the project requirement that CI must not touch GCP

### Tests Added/Passed
- Pending in this round: rerun the updated GitHub Actions dbt workflow with the offline parse command

### Known Issues
- The workflow file remains named `dbt_compile.yml` for continuity with the original Phase 4 task naming, even though it now performs offline dbt parsing
- dbt Core 1.8 does not support `--no-introspect` for `dbt parse`; the workflow must use `--no-populate-cache` instead to stay consistent with the actual CLI surface

## [2026-03-28 Round 29]

### Completed
- Reworked SQLFluff CI to be fully offline and no longer depend on the dbt BigQuery adapter
- Added a dedicated CI SQLFluff config that uses the `jinja` templater with dbt builtins plus a minimal `dbt_utils.generate_surrogate_key()` stub for parseable rendering
- Removed the CI-only `target = ci` override from the default local `.sqlfluff` config so local dbt-templater behavior remains unchanged

### Files Added/Modified
- `.sqlfluff`
- `.sqlfluff.ci`
- `sqlfluff_libs/dbt_utils.py`
- `.github/workflows/lint.yml`
- `dbt/models/staging/stg_grid_metrics.sql`
- `dbt/models/marts/core/fct_grid_metrics.sql`
- `CHANGELOG.md`

### Interface or Behavior Changes
- No API, warehouse, DAG, or real-environment behavior changes
- The lint workflow is now intentionally split from dbt adapter behavior: `sqlfluff` runs offline with Jinja-based dbt stubs, while dbt semantic validation remains the responsibility of the separate `dbt_compile` workflow

### Tests Added/Passed
- Passed: `uv run sqlfluff lint --config .sqlfluff.ci dbt/models`
- Passed: `uv run ruff check .`
- Passed: `uv run pytest -q tests/unit/test_eia_grid_batch_tasks.py tests/unit/test_dbt_testing_contracts.py` (`18 passed`)

### Known Issues
- The dedicated CI SQLFluff config is intentionally less faithful to runtime dbt rendering than the dbt templater; this is a deliberate tradeoff to keep CI fully offline and non-GCP

## [2026-03-28 Round 28]

### Completed
- Fixed the first post-push CI regressions in the early Phase 1 / 2 workflow set
- Updated the Terraform setup action to the current official `v3` major line
- Corrected the dbt-based CI steps so SQLFluff installs dbt packages first and dbt compile uses a structurally valid placeholder service-account key instead of an invalid empty JSON file

### Files Added/Modified
- `.github/workflows/lint.yml`
- `.github/workflows/dbt_compile.yml`
- `.github/workflows/terraform_validate.yml`
- `dbt/profiles.yml`
- `CHANGELOG.md`

### Interface or Behavior Changes
- No API, warehouse, DAG, or real-environment behavior changes
- CI continues to avoid real GCP execution, but now provides a valid placeholder credential shape for parse/compile-only BigQuery adapter initialization
- `Task 4.1` remains in progress overall because Phase 3 serving-layer tests still need future CI expansion

### Tests Added/Passed
- Not run locally in this round: the failing GitHub Actions steps were fixed directly from the concrete CI logs you provided
- Previously still passing locally: `uv run ruff check .`, `uv run pytest -q tests/unit/test_eia_grid_batch_tasks.py tests/unit/test_dbt_testing_contracts.py`, `terraform -chdir=terraform fmt -check -recursive`

### Known Issues
- If GitHub still reports a Node runtime deprecation warning for `hashicorp/setup-terraform@v3`, that warning is upstream-action runtime policy rather than a repository Terraform configuration problem

## [2026-03-28 Round 27]

### Completed
- Started the early `Task 4.1` CI setup for the already accepted Phase 1 / 2 ELT scope
- Added GitHub Actions workflows for linting, dbt compile, and Terraform validation without any real GCP execution path
- Tightened SQLFluff CI templating to use the `ci` dbt target and cleared a repo-wide Ruff failure so `ruff check .` can pass in CI

### Files Added/Modified
- `.github/workflows/lint.yml`
- `.github/workflows/dbt_compile.yml`
- `.github/workflows/terraform_validate.yml`
- `.sqlfluff`
- `tests/integration/test_pipeline_e2e.py`
- `CHANGELOG.md`

### Interface or Behavior Changes
- No API, warehouse-schema, DAG-sequence, or real-environment behavior changes
- GitHub Actions CI is now explicitly non-GCP and limited to syntax, lint, compile, and unit/static validation for the completed ELT phases
- Task `4.1` remains in progress overall because Phase 3 serving-layer tests are expected to extend CI later
- SQLFluff dbt templating now targets `ci` by default so linting does not depend on the real `dev` BigQuery profile

### Tests Added/Passed
- Passed: `uv run ruff check .`
- Passed: `uv run pytest -q tests/unit/test_eia_grid_batch_tasks.py tests/unit/test_dbt_testing_contracts.py` (`18 passed`)
- Passed: `terraform -chdir=terraform fmt -check -recursive`
- Not run locally in this round: `sqlfluff lint`, `dbt deps && dbt compile --target ci`, `terraform init -backend=false`, `terraform validate` because the current request explicitly avoids real-environment paths and the local sandbox blocks external registry/package downloads

### Known Issues
- Final confirmation for the `sqlfluff` / `dbt compile` / `terraform validate` workflow steps is deferred to GitHub Actions or a later local run with external package-registry access

## [2026-03-28 Round 26]

### Completed
- Executed the full heavy integration suite against real Airflow, BigQuery, GCS, and EIA resources with a `12`-window backfill
- Confirmed that the previously corrected heavy idempotent-rerun and heavy backfill validations both pass when run together as the full heavy suite
- Closed the remaining Phase 2 ELT validation gap for smoke + heavy + isolated failure-path coverage

### Files Added/Modified
- `CHANGELOG.md`
- `TEST_RUN_GUIDE.txt`

### Interface or Behavior Changes
- No runtime pipeline interface changes
- No testing contract changes; this round records successful execution of the existing heavy acceptance flow

### Tests Added/Passed
- Passed: `set -a; source .env; set +a; VOLTAGE_HUB_RUN_PIPELINE_TESTS=1 VOLTAGE_HUB_RUN_HEAVY_PIPELINE_TESTS=1 VOLTAGE_HUB_TEST_BACKFILL_HOURS=12 .venv/bin/pytest -rs tests/integration/test_pipeline_e2e.py` (`5 passed, 2 skipped`)

### Known Issues
- `meta.run_metrics`, `meta.freshness_log`, and `meta.anomaly_results` remain append-only by design, so repeated acceptance runs accumulate historical records; serving queries must continue to select latest rows or filter by time/window as documented

## [2026-03-28 Round 25]

### Completed
- Corrected the heavy backfill integration test so its expected `run_metrics` windows match Airflow backfill logical-date semantics
- Added configurable heavy-test backfill end-boundary support and verified the backfill case against a real 2-window run

### Files Added/Modified
- `tests/integration/test_pipeline_e2e.py`
- `DOCS/TESTING.md`
- `DOCS/INTERFACES.md`
- `TEST_RUN_GUIDE.txt`
- `CHANGELOG.md`

### Interface or Behavior Changes
- No runtime pipeline interface changes
- Heavy backfill integration now treats `window_start` as the Airflow backfill logical date, filters for newly created `backfill__*` `run_metrics` rows, and defaults to validating the windows immediately preceding `VOLTAGE_HUB_TEST_BACKFILL_END_BOUNDARY`

### Tests Added/Passed
- Passed: `uv run ruff check tests/integration/test_pipeline_e2e.py`
- Passed: `set -a; source .env; set +a; VOLTAGE_HUB_RUN_PIPELINE_TESTS=1 VOLTAGE_HUB_RUN_HEAVY_PIPELINE_TESTS=1 .venv/bin/pytest -rs tests/integration/test_pipeline_e2e.py -k backfill -vv` (`1 passed, 6 deselected`)

### Known Issues
- The full heavy suite has not yet been re-run as a single command after both fixes; idempotent and backfill have been validated separately

## [2026-03-28 Round 24]

### Completed
- Corrected the heavy idempotent rerun integration test so it establishes its own baseline with the target execution window before comparing the second rerun snapshot
- Confirmed that the first heavy failure was caused by prior smoke coverage mutating the same `observation_date` partition, not by a same-window rerun regression

### Files Added/Modified
- `tests/integration/test_pipeline_e2e.py`
- `CHANGELOG.md`

### Interface or Behavior Changes
- No runtime pipeline interface changes
- Heavy idempotent validation now compares two consecutive runs of the same execution window instead of comparing against a snapshot that may already have been altered by earlier smoke scenarios touching overlapping dates

### Tests Added/Passed
- Passed: `uv run ruff check tests/integration/test_pipeline_e2e.py`
- Passed: `set -a; source .env; set +a; VOLTAGE_HUB_RUN_PIPELINE_TESTS=1 VOLTAGE_HUB_RUN_HEAVY_PIPELINE_TESTS=1 .venv/bin/pytest -rs tests/integration/test_pipeline_e2e.py -k idempotent -vv` (`1 passed, 6 deselected`)

### Known Issues
- Heavy backfill validation still fails because `meta.run_metrics` is missing at least one expected backfilled window row; this remains the next issue to debug

## [2026-03-28 Round 23]

### Completed
- Executed the isolated failure-path integration flow end to end against real Airflow and BigQuery resources
- Verified that the temporary failure-path datasets are deleted after the run and do not remain in the project

### Files Added/Modified
- `tests/integration/test_pipeline_e2e.py`
- `CHANGELOG.md`

### Interface or Behavior Changes
- No runtime pipeline interface changes
- Failure-path freshness validation now uses test-run-relative staleness thresholds and isolated temporary datasets, which allows deterministic source-level warn/error checks without requiring a follow-up smoke recovery run

### Tests Added/Passed
- Passed: `set -a; source .env; set +a; VOLTAGE_HUB_RUN_PIPELINE_TESTS=1 VOLTAGE_HUB_RUN_FAILURE_PATH_PIPELINE_TESTS=1 .venv/bin/pytest -rs tests/integration/test_pipeline_e2e.py` (`5 passed, 2 skipped`)
- Verified: `bq ls --format=prettyjson --project_id=voltage-hub-dev` shows only `raw`, `staging`, `marts`, and `meta` after the failure-path run

### Known Issues
- Heavy rerun/backfill validation remains opt-in and was not executed in this round

## [2026-03-28 Round 22]

### Completed
- Reworked the failure-path freshness integration flow to use isolated temporary datasets instead of mutating the shared development datasets
- Updated the testing documentation and root guide to reflect that failure-path data is now self-cleaning and no longer requires a smoke recovery run

### Files Added/Modified
- `tests/integration/test_pipeline_e2e.py`
- `DOCS/TESTING.md`
- `TEST_RUN_GUIDE.txt`
- `CHANGELOG.md`

### Interface or Behavior Changes
- No runtime pipeline interface changes
- Failure-path freshness checks now create and delete isolated `raw/staging/marts/meta` datasets during the test run, so they can deterministically validate source-level freshness without polluting the shared development environment

### Tests Added/Passed
- Pending: execute the isolated failure-path integration run

### Known Issues
- The failure-path run still validates `dbt source freshness`; it does not yet run the full DAG against the isolated datasets

## [2026-03-28 Round 21]

### Completed
- Corrected the failure-path freshness integration flow so it respects source-level freshness semantics in shared datasets
- The warn/error freshness tests now skip when fresher batches elsewhere in the raw source make a deterministic threshold breach impossible

### Files Added/Modified
- `tests/integration/test_pipeline_e2e.py`
- `TEST_RUN_GUIDE.txt`
- `CHANGELOG.md`

### Interface or Behavior Changes
- No runtime interface changes
- Failure-path freshness tests no longer assume that mutating one raw batch can always force `dbt source freshness` to warn or fail at the whole-source level

### Tests Added/Passed
- Not run yet: post-edit validation pending

### Known Issues
- To deterministically force source-level freshness warn/error in all cases, these tests still need either isolated datasets or a broader source-wide staleness setup

## [2026-03-28 Round 20]

### Completed
- Made the heavy backfill integration window count configurable through `VOLTAGE_HUB_TEST_BACKFILL_HOURS` while keeping the default behavior at 2 hourly windows
- Updated the root test-run guide to document how to pass the backfill duration environment variable inline with the heavy test command

### Files Added/Modified
- `tests/integration/test_pipeline_e2e.py`
- `TEST_RUN_GUIDE.txt`
- `CHANGELOG.md`

### Interface or Behavior Changes
- No runtime pipeline behavior changes
- Heavy integration execution now supports configurable backfill depth via `VOLTAGE_HUB_TEST_BACKFILL_HOURS`; default remains 2 hourly windows

### Tests Added/Passed
- Not run yet: post-edit validation pending

### Known Issues
- Failure-path freshness integration remains opt-in and still requires a recovery smoke run after execution

## [2026-03-28 Round 19]

### Completed
- Added the remaining pending test-flow code for targeted Phase 2 freshness/failure-path validation without enabling those flows in the default smoke suite
- Added a failed-run metrics unit test and opt-in integration scaffolding for freshness warn/error threshold checks

### Files Added/Modified
- `pyproject.toml`
- `tests/unit/test_eia_grid_batch_tasks.py`
- `tests/integration/test_pipeline_e2e.py`
- `CHANGELOG.md`

### Interface or Behavior Changes
- No runtime interface changes
- Integration coverage now distinguishes three opt-in modes: default smoke, heavy rerun/backfill, and targeted failure-path freshness checks

### Tests Added/Passed
- Passed: `uv run python -m py_compile tests/unit/test_eia_grid_batch_tasks.py tests/unit/test_dbt_testing_contracts.py tests/integration/test_pipeline_e2e.py`
- Passed: `uv run ruff check pyproject.toml tests/unit/test_eia_grid_batch_tasks.py tests/unit/test_dbt_testing_contracts.py tests/integration/test_pipeline_e2e.py`
- Passed: `uv run pytest -q tests/unit/test_eia_grid_batch_tasks.py tests/unit/test_dbt_testing_contracts.py tests/integration/test_pipeline_e2e.py` (`18 passed, 7 skipped`)
- Passed: `set -a; source .env; set +a; VOLTAGE_HUB_RUN_PIPELINE_TESTS=1 .venv/bin/pytest -rs tests/integration/test_pipeline_e2e.py` (`3 passed, 4 skipped`)

### Known Issues
- The targeted freshness warn/error integration flows were added as opt-in scaffolding and were not executed in this round
- Heavy rerun/backfill validation remains opt-in and was not executed in this round

## [2026-03-28 Round 18]

### Completed
- Expanded `TESTING.md` to document the still-missing execution flows for real freshness warn/error validation and real failure-path `meta.run_metrics` validation

### Files Added/Modified
- `DOCS/TESTING.md`
- `CHANGELOG.md`

### Interface or Behavior Changes
- No code or interface changes; the testing specification now explicitly distinguishes smoke, heavy, and failure-path validation for Phase 2 control-plane behavior

### Tests Added/Passed
- Not run: documentation-only update

### Known Issues
- The newly documented freshness-threshold and failure-path validation flows are still pending implementation as executable tests or operational checklists

## [2026-03-28 Round 17]

### Completed
- Completed remaining automated test coverage for `TESTING.md` Sections `2.3`, `2.4`, and `2.5`
- Added static contract tests for the required dbt quality gates and source freshness configuration
- Added unit coverage for two-signal freshness logging and warning-only anomaly behavior
- Added the missing smoke-path date-boundary integration test for a window that spans midnight UTC

### Files Added/Modified
- `tests/unit/test_dbt_testing_contracts.py`
- `tests/unit/test_eia_grid_batch_tasks.py`
- `tests/integration/test_pipeline_e2e.py`
- `CHANGELOG.md`

### Interface or Behavior Changes
- No runtime interface or warehouse schema changes
- Smoke integration coverage now includes the documented cross-midnight partition rebuild scenario in addition to the existing single-window and meta-output checks

### Tests Added/Passed
- Passed: `uv run python -m py_compile tests/unit/test_eia_grid_batch_tasks.py tests/unit/test_dbt_testing_contracts.py tests/integration/test_pipeline_e2e.py`
- Passed: `uv run ruff check tests/unit/test_eia_grid_batch_tasks.py tests/unit/test_dbt_testing_contracts.py tests/integration/test_pipeline_e2e.py`
- Passed: `uv run pytest -q tests/unit/test_eia_grid_batch_tasks.py tests/unit/test_dbt_testing_contracts.py tests/integration/test_pipeline_e2e.py` (`17 passed, 5 skipped`)
- Passed: `set -a; source .env; set +a; VOLTAGE_HUB_RUN_PIPELINE_TESTS=1 .venv/bin/pytest -rs tests/integration/test_pipeline_e2e.py` (`3 passed, 2 skipped`)

### Known Issues
- The heavy integration path remains opt-in and was not run in this round: idempotent rerun and multi-window backfill still require `VOLTAGE_HUB_RUN_HEAVY_PIPELINE_TESTS=1`

## [2026-03-28 Round 16]

### Completed
- Aligned the documented Voltage Hub `energy_source` / fuel-code contract with the implemented dbt accepted-values gate by preserving `BIO`, `HPS`, and `HYC` in the published docs

### Files Added/Modified
- `DOCS/SPEC.md`
- `DOCS/INTERFACES.md`
- `DOCS/TESTING.md`
- `CHANGELOG.md`

### Interface or Behavior Changes
- No runtime code changes; the published documentation contract for allowed `energy_source` values now explicitly includes `BIO`, `HPS`, and `HYC` to match the current dbt quality gate

### Tests Added/Passed
- Not run yet: post-edit documentation consistency checks

### Known Issues
- `TESTING.md` Section `2.5` still documents the date-boundary integration scenario as required, but the automated test coverage for that case has not yet been added

## [2026-03-28 Round 15]

### Completed
- Clarified `TESTING.md` Section `2.5` by promoting the date-boundary window rebuild scenario into the formal end-to-end integration test checklist

### Files Added/Modified
- `DOCS/TESTING.md`
- `CHANGELOG.md`

### Interface or Behavior Changes
- No code or interface changes; documentation now treats cross-midnight partition rebuild validation as an explicit `2.5` integration test requirement rather than only a high-risk note

### Tests Added/Passed
- Not run: documentation-only update

### Known Issues
- The date-boundary window integration scenario is now explicitly required in `TESTING.md`, but it is still not implemented as an automated test

## [2026-03-28 Round 14]

### Completed
- Refined the `TESTING.md` Section `2.5` integration harness by separating smoke-path checks from heavier rerun/backfill checks
- Clarified the Airflow execution-timestamp semantics used by the integration tests and aligned the energy-source accepted-values contract with the published interface docs

### Files Added/Modified
- `tests/integration/test_pipeline_e2e.py`
- `pyproject.toml`
- `dbt/models/staging/schema.yml`
- `.env.example`
- `DOCS/TESTING.md`
- `DOCS/INTERFACES.md`
- `DOCS/ARCHITECTURE.md`
- `DOCS/SPEC.md`
- `CHANGELOG.md`

### Interface or Behavior Changes
- No data-plane or API behavior changes; integration tests now use clearer `airflow_execution_date` / extraction-window naming to match Airflow's hourly interval semantics
- Added optional test-only environment variables for smoke vs. heavy integration execution and documented them in the project config references
- The documented `energy_source` contract now explicitly lists the Voltage Hub fuel-code set that the dbt accepted-values gate enforces

### Tests Added/Passed
- Passed: `python -m py_compile tests/integration/test_pipeline_e2e.py`
- Passed: `.venv/bin/ruff check tests/integration/test_pipeline_e2e.py pyproject.toml`
- Passed: `.venv/bin/pytest tests/integration/test_pipeline_e2e.py` (default path: 4 skipped without real-resource env enabled)
- Passed: `VOLTAGE_HUB_RUN_PIPELINE_TESTS=1 .venv/bin/pytest -rs tests/integration/test_pipeline_e2e.py` with smoke scope (`2 passed, 2 skipped`)

### Known Issues
- The heavy rerun/backfill integration path still requires real GCP resources plus `VOLTAGE_HUB_RUN_HEAVY_PIPELINE_TESTS=1`; it remains intentionally opt-in because of runtime cost

## [2026-03-28 Round 13]

### Completed
- Tightened the Phase 2 control-plane contract by documenting the meta-table creation mechanism, formalizing freshness and anomaly edge rules, and replacing dbt artifact path guessing with an explicit `DBT_RUN_RESULTS_PATH` setting

### Files Added/Modified
- `airflow/dags/eia_grid_batch_tasks.py`
- `.env.example`
- `DOCS/ARCHITECTURE.md`
- `DOCS/INTERFACES.md`
- `DOCS/SPEC.md`
- `CHANGELOG.md`

### Interface or Behavior Changes
- No API endpoint contract changes; control-plane documentation now explicitly states that Airflow creates meta tables on demand before writing them
- Formalized the default `data_freshness_status` threshold as 6 hours in the project spec and interfaces contract
- Formalized anomaly edge behavior: the rolling baseline uses the prior 7 calendar days, and missing/zero baselines produce `pct_deviation = NULL` with `anomaly_flag = FALSE`
- Replaced implicit dbt artifact path guessing with explicit configuration via `DBT_RUN_RESULTS_PATH` (default `/opt/airflow/dbt/target/run_results.json`)

### Tests Added/Passed
- Not run: unit, integration, dbt, and Airflow execution tests per current request

### Known Issues
- The new `DBT_RUN_RESULTS_PATH` contract is documented and wired, but it has not yet been exercised through a live Airflow/dbt run in this round

## [2026-03-28 Round 12]

### Completed
- Corrected the `Task 2.1`, `Task 2.2`, `Task 2.3`, and `Task 2.4` control-plane implementation so the DAG behavior and meta-table documentation align more strictly with `SPEC.md`, `ARCHITECTURE.md`, and `INTERFACES.md`

### Files Added/Modified
- `airflow/dags/eia_grid_batch.py`
- `airflow/dags/eia_grid_batch_tasks.py`
- `dbt/models/meta/schema.yml`
- `CHANGELOG.md`

### Interface or Behavior Changes
- No serving API contract changes; `record_run_metrics` can now persist `"failed"` status on unsuccessful runs instead of only ever writing `"success"`
- `check_anomalies` is now warning-only in task behavior: internal failures are logged and returned as warnings rather than raising exceptions that stop the DAG
- `check_anomalies` now reads mart aggregate tables instead of `marts.fct_grid_metrics`, and its rolling baseline uses the prior 7 calendar days rather than the prior 7 rows
- `dbt/models/meta/schema.yml` now documents the meta tables as dbt `sources` instead of dbt `models`, matching the documented ownership that Airflow creates and writes these tables
- Assumption: anomaly detection should evaluate the documented mart aggregate layer using daily `demand` from `marts.agg_load_daily` plus daily total `generation` rolled up from `marts.agg_generation_mix`, because the meta anomaly contract includes `metric_name` but no `energy_source`

### Tests Added/Passed
- Passed: `uv run python -m py_compile airflow/dags/eia_grid_batch.py airflow/dags/eia_grid_batch_tasks.py`
- Not run: full unit, integration, dbt, or Airflow execution tests per current request

### Known Issues
- `meta.run_metrics` still depends on Airflow task-state inspection and available dbt artifacts; if you later want stricter failure-path guarantees, the next useful step would be a targeted Airflow-path test rather than a full suite run

## [2026-03-28 Round 11]

### Completed
- Completed `Task 2.1`, `Task 2.2`, `Task 2.3`, and `Task 2.4` by replacing the control-plane placeholders with real meta-table writes, dual-signal freshness logging, and warning-only anomaly detection
- Completed `TESTING.md` Section `2.3` by aligning dbt quality gates with the required staging and mart invariants
- Completed `TESTING.md` Section `2.5` by adding executable end-to-end integration tests for single-window runs, meta outputs, idempotent reruns, and two-window backfill validation

### Files Added/Modified
- `airflow/dags/eia_grid_batch.py`
- `airflow/dags/eia_grid_batch_tasks.py`
- `dbt/models/staging/schema.yml`
- `dbt/models/marts/core/schema.yml`
- `dbt/models/meta/schema.yml`
- `tests/integration/test_pipeline_e2e.py`
- `pyproject.toml`
- `DOCS/TASKS.md`
- `CHANGELOG.md`

### Interface or Behavior Changes
- No serving API contract changes; the DAG now persists `meta.pipeline_state`, `meta.run_metrics`, `meta.freshness_log`, and `meta.anomaly_results` according to the documented schemas
- Added the missing staging `energy_source` accepted-values gate and mart grain-uniqueness gate required by `TESTING.md` / `SPEC.md`
- Assumption: the consumer-facing `fresh` versus `stale` classification in `meta.freshness_log` uses the documented 6-hour warn threshold for both pipeline freshness and data freshness because no separate data-freshness threshold is specified
- Assumption: the EIA fuel-type endpoint emits the observed short fuel codes (`BAT`, `BIO`, `COL`, `GEO`, `HPS`, `HYC`, `NG`, `NUC`, `OES`, `OIL`, `OTH`, `PS`, `SNB`, `SUN`, `UES`, `UNK`, `WAT`, `WNB`, `WND`) within current project scope

### Tests Added/Passed
- Added: `tests/integration/test_pipeline_e2e.py`
- Passed: `python -m py_compile airflow/dags/eia_grid_batch.py airflow/dags/eia_grid_batch_tasks.py tests/integration/test_pipeline_e2e.py tests/unit/test_eia_grid_batch_tasks.py`
- Passed: `.venv/bin/ruff check airflow/dags/eia_grid_batch.py airflow/dags/eia_grid_batch_tasks.py tests/integration/test_pipeline_e2e.py`
- Passed: `.venv/bin/pytest tests/unit/test_eia_grid_batch_tasks.py`
- Passed: `VOLTAGE_HUB_RUN_PIPELINE_TESTS=1 .venv/bin/pytest -rs tests/integration/test_pipeline_e2e.py`
- Verified: latest `meta.run_metrics` rows record non-zero dbt model/test counts and bytes processed

### Known Issues
- `airflow dags test` interprets its timestamp argument as the DAG run logical date (`data_interval_end` for the hourly schedule), so integration tests must derive the actual extraction window start as one hour earlier

## [2026-03-28 Round 10]

### Completed
- Completed `Task 1.6` by implementing the mart core models, aggregate models, relationship tests, and mart dataset routing for dbt
- Completed `Task 1.7` by creating the project `Makefile`, validating all target command mappings, and running the real `dbt-build`, `dbt-docs`, and `lint` targets

### Files Added/Modified
- `dbt/dbt_project.yml`
- `dbt/macros/generate_schema_name.sql`
- `dbt/models/staging/stg_grid_metrics.sql`
- `dbt/models/marts/core/fct_grid_metrics.sql`
- `dbt/models/marts/core/dim_region.sql`
- `dbt/models/marts/core/dim_energy_source.sql`
- `dbt/models/marts/core/schema.yml`
- `dbt/models/marts/aggregates/agg_load_hourly.sql`
- `dbt/models/marts/aggregates/agg_load_daily.sql`
- `dbt/models/marts/aggregates/agg_generation_mix.sql`
- `dbt/models/marts/aggregates/agg_top_regions.sql`
- `dbt/models/marts/aggregates/schema.yml`
- `.sqlfluff`
- `Makefile`
- `DOCS/TASKS.md`
- `CHANGELOG.md`

### Interface or Behavior Changes
- No API contract changes; implemented the documented mart contracts in `marts.fct_grid_metrics`, `marts.dim_region`, `marts.dim_energy_source`, `marts.agg_load_hourly`, `marts.agg_load_daily`, `marts.agg_generation_mix`, and `marts.agg_top_regions`
- Added `dbt` macro override so folder `+schema` values resolve directly to the documented BigQuery datasets (`staging`, `marts`) instead of dbt's default concatenated schema names
- Assumption: `agg_generation_mix` exposes `daily_total_generation` plus `unit` at the documented grain `region × observation_date × energy_source` so the column naming stays aligned with the daily aggregate convention used by `daily_total_load`
- Assumption: `Makefile` backfills require explicit `START_DATE` and `END_DATE` inputs so CLI usage stays deterministic across shells and environments
- Assumption: `agg_top_regions.rank` uses BigQuery `rank()` semantics, so ties share the same rank and skip the next value

### Tests Added/Passed
- Passed: `docker compose exec airflow-webserver dbt deps --project-dir /opt/airflow/dbt --profiles-dir /opt/airflow/dbt`
- Passed: `docker compose exec airflow-webserver dbt build --project-dir /opt/airflow/dbt --profiles-dir /opt/airflow/dbt --target dev --vars '{"batch_date": "2026-03-27"}'`
- Passed: `docker compose exec airflow-webserver dbt docs generate --project-dir /opt/airflow/dbt --profiles-dir /opt/airflow/dbt --target dev`
- Passed: `make dbt-build BATCH_DATE=2026-03-27`
- Passed: `make dbt-docs`
- Passed: `make lint`
- Passed: `make -n up down build backfill dbt-build dbt-docs dbt-deps lint terraform-init terraform-apply terraform-destroy clean`
- Passed: `uv run ruff check .`

### Known Issues
- Earlier validation runs created tables in misrouted datasets such as `staging_staging` / `staging_marts` before the schema-name macro fix; these legacy datasets were not deleted in this round to avoid destructive cleanup outside the requested scope

## [2026-03-28 Round 9]

### Completed
- Completed `Task 1.4` by adding the `eia_grid_batch` Airflow DAG with the required task order, default schedule/retry/timeout settings, and successful end-to-end DAG validation
- Completed `Task 1.5` by implementing the dbt staging project, source definition, profile, canonical staging model, and staging data tests

### Files Added/Modified
- `airflow/dags/eia_grid_batch.py`
- `dbt/dbt_project.yml`
- `dbt/packages.yml`
- `dbt/profiles.yml`
- `dbt/models/sources.yml`
- `dbt/models/staging/stg_grid_metrics.sql`
- `dbt/models/staging/schema.yml`
- `DOCS/TASKS.md`
- `CHANGELOG.md`

### Interface or Behavior Changes
- No interface contract changes; this round implemented the existing Airflow DAG and `staging.stg_grid_metrics` contract from `SPEC.md` / `INTERFACES.md`
- Assumption: the configurable DAG schedule and optional explicit start date are read from Airflow Variables `pipeline_schedule` and `pipeline_start_date`, with defaults of `@hourly` and `BACKFILL_DAYS=7`
- Assumption: until Phase 2 tasks are implemented, `check_anomalies`, `record_run_metrics`, and `update_pipeline_state` run as no-op placeholders so the required DAG chain can execute end to end without inventing meta-table writes early
- Assumption: non-fuel region metrics are standardized to snake_case labels derived from upstream `type_name` so observed categories such as `demand`, `day_ahead_demand_forecast`, `net_generation`, and `total_interchange` remain explicit in staging

### Tests Added/Passed
- Passed: `uv run ruff check airflow/dags/eia_grid_batch.py airflow/dags/eia_grid_batch_tasks.py`
- Passed: `uv run python -m py_compile airflow/dags/eia_grid_batch.py airflow/dags/eia_grid_batch_tasks.py`
- Passed: `docker compose exec airflow-webserver python -c 'from airflow.models import DagBag; ...'` confirmed `eia_grid_batch` loads with no import errors
- Passed: `docker compose exec airflow-webserver dbt deps --project-dir /opt/airflow/dbt --profiles-dir /opt/airflow/dbt`
- Passed: `docker compose exec airflow-webserver dbt build --project-dir /opt/airflow/dbt --profiles-dir /opt/airflow/dbt --target dev --vars '{"batch_date": "2026-03-27"}'`
- Passed: `docker compose exec airflow-webserver airflow dags test eia_grid_batch 2026-03-27T02:00:00+00:00`

### Known Issues
- `Task 2.2`, `Task 2.3`, and `Task 2.4` still need the real meta-table writers for run metrics, pipeline state, freshness logging, and anomaly detection; the DAG currently preserves those task slots with explicit placeholders

## [2026-03-28 Round 8]

### Completed
- Completed `TESTING.md` Section 2.2 unit-test coverage for extraction and loading helpers in `airflow/dags/eia_grid_batch_tasks.py`

### Files Added/Modified
- `tests/unit/test_eia_grid_batch_tasks.py`
- `tests/fixtures/eia_response.json`
- `CHANGELOG.md`

### Interface or Behavior Changes
- No interface changes

### Tests Added/Passed
- Added: pytest coverage for API request construction, retry handling, response validation, GCS raw landing, and BigQuery raw load configuration
- Passed: `uv run pytest tests/unit/test_eia_grid_batch_tasks.py`
- Passed: `uv run ruff check tests/unit/test_eia_grid_batch_tasks.py`

### Known Issues
- None

## [2026-03-28 Round 7]

### Completed
- Consolidated Task 1.3 schema access to a single mounted source and removed the temporary duplicate schema copy
- Recreated the existing Airflow containers without rebuilding images so the new schema mount took effect
- Re-verified Task 1.3 end to end using the single mounted schema path

### Files Added/Modified
- `airflow/dags/eia_grid_batch_tasks.py`
- `airflow/schemas/raw_eia_batch.json`
- `docker-compose.yml`
- `CHANGELOG.md`

### Interface or Behavior Changes
- Airflow now reads the raw BigQuery schema only from `/opt/airflow/schemas/raw_eia_batch.json`
- Docker Compose now mounts `./airflow/schemas` into both `airflow-webserver` and `airflow-scheduler`

### Tests Added/Passed
- Passed: `uv run ruff check airflow/dags/eia_grid_batch_tasks.py`
- Passed: `uv run python -m py_compile airflow/dags/eia_grid_batch_tasks.py`
- Passed: `docker compose config`
- Passed: `docker compose up -d airflow-webserver airflow-scheduler`
- Passed: live extraction for window `2026-03-27T01:00:00+00:00` to `2026-03-27T02:00:00+00:00` using `/opt/airflow/schemas/raw_eia_batch.json`
- Passed: live GCS landing to `gs://voltage-hub-raw/voltage-hub/raw/year=2026/month=03/day=27/window=2026-03-27T01:00:00+00:00/batch.json`
- Passed: live BigQuery load to `voltage-hub-dev.raw.eia_grid_batch$20260327` with `1476` output rows

### Known Issues
- The raw load path uses newline-delimited JSON at `batch.json` so it can be consumed directly by `bigquery.Client.load_table_from_uri()`

## [2026-03-28 Round 6]

### Completed
- Refined the Terraform testing instruction for Task 1.1 to prefer avoiding destructive reprovision instead of banning it outright

### Files Added/Modified
- `AGENTS.md`
- `CHANGELOG.md`

### Interface or Behavior Changes
- Updated the AGENTS.md caution so later testing should avoid `terraform destroy` when possible, but may use it as a last resort after warning the user
- Documented that if infrastructure is recreated, the user must reconfigure the service account JSON key and restart `docker compose` so the containers remount it

### Tests Added/Passed
- None

### Known Issues
- None

## [2026-03-28 Round 5]

### Completed
- Task 1.3 implementation completed for `extract_grid_batch`, `land_raw_to_gcs`, `load_to_bq_raw`, and `airflow/schemas/raw_eia_batch.json`
- Task 1.3 acceptance verified against the existing Airflow container, GCS bucket, and BigQuery raw dataset

### Files Added/Modified
- `airflow/dags/eia_grid_batch_tasks.py`
- `airflow/schemas/raw_eia_batch.json`
- `docker-compose.yml`
- `DOCS/TASKS.md`
- `CHANGELOG.md`

### Interface or Behavior Changes
- Added the explicit raw landing schema file for `raw.eia_grid_batch`
- Updated Docker Compose to mount `airflow/schemas` into both Airflow services at `/opt/airflow/schemas`
- Implemented raw extraction helpers with required retry/backoff and timeout behavior
- Assumption: `extract_grid_batch` combines EIA `region-data` rows and `fuel-type-data` rows into the shared raw contract so Phase 1 can support both load and generation-source use cases
- Assumption: fuel-type rows are recorded with `type='generation'`, `type_name='Generation'`, and `fueltype_name` sourced from the upstream `type-name` field

### Tests Added/Passed
- Passed: `uv run ruff check airflow/dags/eia_grid_batch_tasks.py`
- Passed: `uv run python -m py_compile airflow/dags/eia_grid_batch_tasks.py`
- Passed: `docker compose config`
- Passed: `docker compose up -d airflow-webserver airflow-scheduler` applied the new `airflow/schemas` bind mount without rebuilding images
- Passed: live extraction for window `2026-03-27T00:00:00+00:00` to `2026-03-27T01:00:00+00:00` returned `1477` rows
- Passed: live GCS landing to `gs://voltage-hub-raw/voltage-hub/raw/year=2026/month=03/day=27/window=2026-03-27T00:00:00+00:00/batch.json`
- Passed: live BigQuery load to `voltage-hub-dev.raw.eia_grid_batch$20260327` with `1477` output rows
- Passed: live extraction for window `2026-03-27T01:00:00+00:00` to `2026-03-27T02:00:00+00:00` confirmed runtime schema path `/opt/airflow/schemas/raw_eia_batch.json` and loaded `1476` rows
- Passed: read-only verification confirmed the GCS object exists (`935326` bytes)
- Passed: read-only verification confirmed `raw.eia_grid_batch` contains `1477` rows for `batch_date = 2026-03-27`

### Known Issues
- The raw load path uses newline-delimited JSON at `batch.json` so it can be consumed directly by `bigquery.Client.load_table_from_uri()`

## [2026-03-28 Round 4]

### Completed
- Updated project and resource naming references in documentation to align with the formal Voltage Hub name

### Files Added/Modified
- `DOCS/SPEC.md`
- `DOCS/ARCHITECTURE.md`
- `DOCS/TASKS.md`
- `DOCS/INTERFACES.md`
- `CHANGELOG.md`

### Interface or Behavior Changes
- Updated documentation examples for `GCS_BUCKET_NAME` from `eia-grid-raw` to `voltage-hub-raw`
- Updated documented GCS raw landing path prefix from `eia-grid/raw/...` to `voltage-hub/raw/...`
- Updated the repository root naming example from `eia-grid-data-product/` to `voltage-hub/`
- Updated the documented dbt project identifier example from `eia_grid` to `voltage_hub`
- Preserved data-domain and contract names such as `EIA Grid Data`, `eia_grid_batch`, and `eia_grid_batch.py`

### Tests Added/Passed
- Passed: repository-wide search verification for outdated project/resource naming references in `DOCS/`

### Known Issues
- Document titles had already been updated separately before this round and were not changed here

## [2026-03-28 Round 3]

### Completed
- Re-ran `TESTING.md` Section 2.1 infrastructure validation against the current Terraform and Docker Compose setup

### Files Added/Modified
- `CHANGELOG.md`

### Interface or Behavior Changes
- No interface changes

### Tests Added/Passed
- Passed: `terraform -chdir=terraform plan -var-file=terraform.tfvars`
- Passed: `terraform -chdir=terraform apply -auto-approve -var-file=terraform.tfvars` with direct GCP verification of the bucket, datasets, and runtime service account
- Passed: `terraform -chdir=terraform destroy -auto-approve -var-file=terraform.tfvars`
- Passed: `terraform -chdir=terraform apply -auto-approve -var-file=terraform.tfvars` to restore the development environment after cleanup validation
- Passed: post-restore `terraform -chdir=terraform plan -var-file=terraform.tfvars` returned no changes
- Passed: `docker compose up -d`
- Passed: `docker compose ps`
- Passed: `curl http://127.0.0.1:8080/health` returned `200`
- Passed: `docker compose exec airflow-webserver dbt deps --project-dir /opt/airflow/dbt`

### Known Issues
- Direct post-destroy BigQuery absence was verified with `bq ls`; service account absence check is limited by the active GCP account permissions after deletion
- Docker Compose stack remains running for the next development step

## [2026-03-28 Round 2]

### Completed
- Task 1.2 re-verified against the current local `.env` and mounted service account JSON key

### Files Added/Modified
- `CHANGELOG.md`

### Interface or Behavior Changes
- No interface changes

### Tests Added/Passed
- Passed: `docker compose config`
- Passed: `docker compose build`
- Passed: `docker compose up -d`
- Passed: `curl http://127.0.0.1:8080/health` returned `200`
- Passed: `docker compose exec airflow-webserver dbt deps --project-dir /opt/airflow/dbt`

### Known Issues
- Docker Compose stack is left running for the next development step

## [2026-03-28 Round 1]

### Completed
- Task 1.1 completed: Terraform variables, resources, outputs, example tfvars, and real apply/destroy verification
- Task 1.2 completed: Dockerfile, Compose stack, `.env.example`, `.gitignore` updates, Airflow/dbt mount skeleton, and container verification

### Files Added/Modified
- `terraform/variables.tf`
- `terraform/main.tf`
- `terraform/outputs.tf`
- `terraform/terraform.tfvars.example`
- `terraform/terraform.tfvars`
- `docker/Dockerfile`
- `docker-compose.yml`
- `.env.example`
- `.gitignore`
- `AGENTS.md`
- `DOCS/TASKS.md`
- `CHANGELOG.md`
- `dbt/dbt_project.yml`
- `dbt/packages.yml`

### Interface or Behavior Changes
- Added Terraform outputs for bucket name, dataset IDs, and runtime service account email
- Added canonical environment variable documentation in `.env.example`, including `GCS_BUCKET_NAME` and `PORT`
- Added local Airflow runtime definition with `LocalExecutor` and fixed service account mount path `/opt/airflow/keys/service-account.json`
- Updated naming introduced in this round to use the Voltage Hub project identity instead of the earlier temporary EIA naming
- Refined runtime naming to use `voltage-hub-runtime` and `voltage-hub-raw` style identifiers
- Assumption: Minimal `dbt/dbt_project.yml` and `dbt/packages.yml` placeholders were added so `dbt deps` can run before Task 1.5 implements the full dbt project

### Tests Added/Passed
- Passed: `terraform -chdir=terraform init`
- Passed: `terraform -chdir=terraform plan -var-file=terraform.tfvars`
- Passed: `terraform -chdir=terraform apply -auto-approve -var-file=terraform.tfvars`
- Passed: resource existence checks for the created bucket, datasets, and service account
- Passed: `terraform -chdir=terraform destroy -auto-approve -var-file=terraform.tfvars`
- Passed: post-destroy checks confirming bucket, datasets, and service account were removed
- Passed: `docker compose config`
- Passed: `docker compose build`
- Passed: `docker compose up -d`
- Passed: `curl http://127.0.0.1:8080/health` returned `200`
- Passed: `docker compose exec airflow-webserver dbt deps --project-dir /opt/airflow/dbt`

### Known Issues
- Docker image build completed with pip dependency conflict warnings around `protobuf` in the base Airflow image; build and runtime validation still succeeded for Task 1.2
- Minimal `dbt/dbt_project.yml` and `dbt/packages.yml` are placeholders for Task 1.5 and should be expanded there
