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
