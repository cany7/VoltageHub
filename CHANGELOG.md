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
