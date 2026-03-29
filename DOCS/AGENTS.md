# AGENTS.md — VoltageHub

---

## 1. Document Reading Order

Before writing any code, read these documents in this order:

1. **`DOCS/SPEC.md`** — ultimate source of truth. If any other document contradicts SPEC.md, SPEC.md wins.
2. **`DOCS/ARCHITECTURE.md`** — system structure, component boundaries, data flow, design decisions.
3. **`DOCS/TASKS.md`** — what to build, in what order, with acceptance criteria.
4. **`DOCS/INTERFACES.md`** — table schemas, API contracts, GCS paths, config schema. Reference this when writing any code that reads/writes data.
5. **`DOCS/TESTING.md`** — what to test, how, and what must pass before a milestone is done.
6. **`DOCS/CHANGELOG.md`**  — what previous agents built, what changed, what is still unresolved. Read this before starting any work.

---

## 2. How to Work with TASKS.md

- **Do not re-plan the project.** Tasks are already decomposed. Pick up from where the last agent left off.
- **Work phase by phase, task by task.** Complete one task fully before starting the next.
- **Check dependency order.** Some tasks depend on earlier ones. The dependency graph is at the bottom of TASKS.md.
- **Mark tasks as complete.** When you finish a task, check it off in TASKS.md (`[x]`). Mark in-progress tasks with `[/]`.
- **Verify acceptance criteria.** Each task has acceptance criteria. Do not consider a task done until all criteria are met.
- **Do not skip phases.** Phases are ordered by dependency. Phase 2 depends on Phase 1 outputs. Phase 3 depends on Phase 2 outputs.

---

## 3. Source of Truth Priority

When making implementation decisions:

1. **SPEC.md** — if SPEC.md specifies behavior, follow it exactly
2. **INTERFACES.md** — if INTERFACES.md specifies a schema or contract, use those exact field names and types
3. **ARCHITECTURE.md** — for component boundaries, data flow, and design decisions
4. **TASKS.md** — for scope and ordering

If you encounter a conflict between documents, SPEC.md is authoritative. Flag the conflict in your changelog entry.

---

## 4. Assumptions Policy

- **Do not invent features, endpoints, tables, or fields** not specified in SPEC.md or INTERFACES.md.
- **If you need to make an implementation choice** not covered by the spec (e.g., error message format, log level, internal function naming), make the smallest reasonable choice and document it.
- **Mark all assumptions explicitly** with the label `Assumption:` in code comments or commit messages.
- **Allowed assumptions:** internal function signatures, variable naming conventions, log formatting, test file organization, minor utility helpers.
- **Not allowed without spec support:** new API endpoints, new BigQuery tables, changing partition strategies, adding external dependencies, altering the DAG task sequence.

---

## 5. Changes to Avoid

Unless explicitly required by SPEC.md:

- Do not add new dependencies beyond those listed in the tech stack (SPEC Section 4)
- Do not change the DAG task sequence or add new DAG tasks
- Do not create new BigQuery datasets beyond `raw`, `staging`, `marts`, `meta`
- Do not add new API endpoints beyond those specified
- Do not introduce streaming, async workers, or external caching
- Do not change partition keys or clustering strategies
- Do not change the GCS path convention
- Do not split the serving API into multiple services

---

## 6. What to Update When Things Change

| If you change...                    | Also update...                                                      |
|-------------------------------------|---------------------------------------------------------------------|
| A BigQuery table schema             | `INTERFACES.md` table contract, `airflow/schemas/` (if raw), dbt `schema.yml` |
| An API endpoint signature           | `INTERFACES.md` endpoint contract, Pydantic schemas, tests          |
| A dbt model                         | `schema.yml` descriptions and tests, INTERFACES.md if schema changed |
| Partition or clustering strategy    | `ARCHITECTURE.md`, `INTERFACES.md`, affected dbt model configs      |
| DAG task sequence                   | `ARCHITECTURE.md` data flow diagram, `TASKS.md` if acceptance criteria affected |
| Environment variables               | `.env.example`, `INTERFACES.md` config schema, `ARCHITECTURE.md` config section |
| Error handling behavior             | `ARCHITECTURE.md` error handling section, `TESTING.md` edge cases   |

---

## 7. Project-Specific Cautions

1. **Partition rebuild scoping is critical.** Every incremental dbt model must scope its rebuild to the affected `observation_date` set, not all partitions. Incorrect scoping causes silent data corruption or unnecessary cost. Always test with extraction windows that span date boundaries.

2. **The serving API reads only `agg_*` and `meta.*` tables.** It never queries `raw`, `staging`, or `fct_grid_metrics`. If you find yourself writing a query against fact tables in the serving layer, stop — the data should come from an aggregate table.

3. **`max_active_runs=1` is intentional.** Do not change this to parallelize backfill without also changing the partition strategy from `WRITE_TRUNCATE` to `WRITE_APPEND` with conflict resolution.

4. **Freshness has two signals.** Pipeline freshness (`_ingestion_timestamp`) and data freshness (`observation_timestamp`) are distinct. The combined `freshness_status` in API responses is the worse of the two. Do not collapse them into a single check.

5. **Anomaly detection is warning-only.** It must not fail the DAG. If you add anomaly checks, ensure they log results but do not raise exceptions that would stop the pipeline.

6. **Raw schema reflects source shape, not canonical shape.** Do not normalize or pivot fields in the raw table. That is the staging layer's job. The raw layer preserves what the EIA API returned.

7. **Meta tables are not dbt models.** They are written to by Airflow PythonOperator tasks. Do not try to create them as dbt models. The `dbt/models/meta/schema.yml` documents their structure but does not create or populate them.

8. **dbt `deps` must run before any dbt command.** Ensure this happens either in the Docker entrypoint or as a Makefile target after `docker compose up`.

9. **Avoid destructive Terraform re-validation unless it is truly required.** Task 1.1 infrastructure has already been confirmed, so later testing should avoid `terraform destroy` / full reprovision whenever possible. Some later GCS / BigQuery / IAM issues may still require reprovisioning, but this should be treated as a last resort and surfaced to the user before proceeding. If infrastructure must be recreated, tell the user they need to regenerate and place the service account JSON key again, then restart `docker compose` so the containers pick up the re-mounted key file before continuing validation.

---

## 8. Iteration Handoff — CHANGELOG.md

After each completed implementation round, you **must** create or append to the top-level `CHANGELOG.md` file in the project root.

### Format

Each entry must include:

```
## [Date or Round Identifier]

### Completed
- Which task(s) or phase(s) were completed (reference TASKS.md identifiers)

### Files Added/Modified
- List of key files added or modified

### Interface or Behavior Changes
- Any changes to API contracts, table schemas, partition strategies, or config

### Tests Added/Passed
- Which tests were added and their results

### Known Issues
- Unresolved issues, blockers, or deferred items for the next iteration
```

### Rules

- Append new entries at the **top** of the file (newest first)
- Keep entries concise and operational — no prose, no marketing
- Reference task identifiers from TASKS.md (e.g., "Task 1.3", "Phase 2")
- If you changed any interface, explicitly note it so the next agent knows
- If you discovered a bug or edge case you did not fix, document it under Known Issues

---

## 9. Code Style and Local Tooling

- **Python version:** 3.11 (matches Airflow container runtime).
- **Local Python tooling:** Use `uv` as the package manager. Run commands via `uv run ...` (e.g., `uv run ruff check`, `uv run uvicorn app.main:app`). The serving layer declares dependencies in `serving-fastapi/pyproject.toml`, not `requirements.txt`.
- **Container builds:** Airflow Dockerfile installs Python deps via pip inside the container. This is a container build detail — do not mix it with the local `uv`-based workflow.
- **Python style:** Follow `ruff` defaults. Use type hints. Use `snake_case` for functions and variables.
- **SQL (dbt):** Follow `sqlfluff` BigQuery dialect rules. Use lowercase keywords. Use CTEs over nested subqueries.
- **Terraform:** Run `terraform fmt` before committing.
- **Config naming:** The serving API port env var is `PORT` (not `SERVER_PORT`). The GCS bucket env var is `GCS_BUCKET_NAME`. Use these exact names in code and config files.
- **Naming consistency:** Use the exact table names, field names, and endpoint paths from INTERFACES.md. Do not rename them.
- **Comments:** Explain *why*, not *what*. Mark assumptions with `Assumption:`.

---

## 10. Project Identity Notes

- **Current GCP project ID:** `voltage-hub-dev`
- **Naming baseline:** use the current project name **Voltage Hub** for new resource names, labels, service accounts, local project identifiers, and other naming choices.
- **Naming examples:** `voltage-hub-raw` for the raw bucket, `voltage-hub-runtime` for the runtime service account, and `voltage_hub` for local/dbt project identifiers where underscores are required.
- **Temporary legacy wording:** `eia grid data product` / `eia-grid-*` was temporary wording and should not be used for new naming unless a source document still requires it as an external contract.
