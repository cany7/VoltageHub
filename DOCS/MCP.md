# MCP.md — VoltageHub

---

## 1. Purpose

This document defines the design of the VoltageHub MCP server.

It exists to complement the system spec:

- `SPEC` defines product scope, architecture, and system requirements
- `MCP.md` defines the MCP-specific interface design and implementation constraints

The MCP server is a read-only serving interface for LLM agents. It exposes fixed, curated capabilities over precomputed warehouse outputs. It is not an ad hoc query engine.

---

## 2. Scope

The MCP server:

- uses the Model Context Protocol over `stdio`
- exposes read-only Tools and Resources
- reads only from precomputed `marts.agg_*` tables, serving-safe dimension tables, and `meta.*` tables
- shares business logic and data semantics with the REST serving layer
- is designed for LLM-friendly interaction, not human-operated CLI use

The MCP server does not:

- expose HTTP, SSE, or other remote MCP transports
- execute arbitrary SQL
- query `fct_grid_metrics` directly
- perform runtime aggregation beyond lightweight shaping of precomputed results
- mutate warehouse state

---

## 3. Design Goals

The MCP server should:

- let an agent safely answer common analytical questions about load, generation mix, anomalies, freshness, and pipeline state
- guide the model toward the right tool before it calls one
- use parameter names the model can understand from natural language
- return outputs the model can digest quickly without losing access to structured detail
- preserve the same underlying data definitions used by the REST API

The design is intentionally biased toward correctness and predictability over flexibility.

---

## 4. Relationship to the Existing Serving Layer

VoltageHub already has a serving layer with these boundaries:

- routers: transport-level request handling
- services: validation, metadata shaping, response semantics
- repositories: read-only BigQuery access

The MCP server should be implemented as another interface layer over the same service logic.

Recommended implementation approach for v1:

- implement it in Python 3.11+
- organize it as a dedicated package under `mcp/`
- reuse shared repository / service logic from the serving layer
- support a clean local developer workflow that GitHub users can run after cloning the repo

Recommended dependency direction:

```text
BigQuery repositories -> domain/services -> FastAPI REST adapters
BigQuery repositories -> domain/services -> MCP stdio adapters
```

Important rules:

- the MCP server should not call the REST API over HTTP
- the MCP server should not duplicate SQL already defined in serving repositories unless there is a deliberate new capability
- core business capabilities, freshness semantics, and core metadata meanings should stay aligned with REST
- MCP may add agent-facing safety semantics in the adapter layer, including summaries, truncation markers, normalization, defaults, and size guards, even when REST does not expose those fields directly

This keeps REST and MCP contract-compatible at the business level even when their output envelopes differ.

---

## 5. Data Access Constraints

The MCP server is limited to the same serving-safe aggregate and control-plane reads as the REST API, plus serving-safe dimension reads for schema resources.

Allowed tables:

- `marts.agg_load_hourly`
- `marts.agg_load_daily`
- `marts.agg_generation_mix`
- `marts.agg_top_regions`
- `marts.dim_region` for schema resources and region normalization support
- `marts.dim_energy_source` for schema resources
- `meta.freshness_log`
- `meta.pipeline_state`
- `meta.anomaly_results`

Disallowed direct reads:

- `raw.*`
- `staging.*`
- `marts.fct_grid_metrics`

Rationale:

- serving should remain cheap, stable, and predictable
- all heavy computation belongs in ELT/dbt
- the MCP layer should not become a second analytics engine

---

## 6. Transport

The MCP server uses:

- transport: `stdio`
- process model: standalone process
- communication model: local MCP-compatible agent client communicates through stdin/stdout

Recommended runtime model for v1:

- local development should use `uv run`
- a typical local command shape is `cd mcp && uv sync --dev && uv run voltagehub-mcp`
- for this repository, agent-host integration should also use `uv run` from the checked-out `mcp/` directory because the MCP package is not published
- a typical host-side startup shape is `command: "uv"` with `args: ["run", "voltagehub-mcp"]` and `cwd` pointing at `/absolute/path/to/voltage-hub/mcp`
- in this model, the host application is responsible for executing the configured command and attaching to the MCP process over stdio; the model only uses the exposed tools/resources once the process is running

Implications:

- no additional network port is required
- no HTTP authentication layer is needed in this design
- startup and operational model should stay simple
- clone-and-run usage is realistic once the user has installed `uv`, synced dependencies in `mcp/`, and provided working GCP credentials

---

## 7. Tool Design Principles

### 7.1 LLM-Optimized Descriptions

Each tool description must explain:

- when the tool should be used
- what kind of question it answers
- when a neighboring tool is a better fit

Bad description style:

- "Returns rows from `agg_load_daily`."

Good description style:

- "Use this when the user wants load trends for a specific region over time. Do not use it for top-N regional ranking questions."

This is important because tool selection is part of the interface contract for agents.

### 7.2 LLM-Friendly Parameters

Tool inputs should use business-readable names, not implementation names.

Preferred examples:

- `region`
- `start_date`
- `end_date`
- `time_granularity`
- `top_n`
- `anomaly_only`

Avoid:

- warehouse table names
- internal column names when they are awkward for agents
- enum values that require warehouse knowledge

Enum values should be natural-language-friendly, such as:

- `daily`
- `hourly`
- `fresh`
- `stale`

Where useful, the implementation may normalize human-friendly values into canonical internal values.

### 7.3 MCP-to-REST Translation Layer

The MCP interface is allowed to use different parameter names from REST as long as it maps to the same shared service semantics.

Examples:

- MCP `time_granularity` may map to REST/service `granularity`
- MCP `top_n` may map to REST/service `limit`
- MCP `anomaly_only` may map to the same boolean concept exposed by REST

This means:

- business meaning must stay aligned
- transport field names do not need to be identical
- the MCP adapter is responsible for parameter normalization and translation before calling shared service logic

### 7.4 Deterministic Summaries

`summary` and `highlights` should be deterministic, template-driven compressions of returned data, not open-ended prose generation.

Rules:

- `summary.main_takeaway` must be generated from `data`, `metadata`, or explicitly derived fields
- `highlights` should contain at most 3 items
- each highlight must map back to returned `data`, `metadata`, or documented derived values
- highlights must not introduce new analytical claims that cannot be reconstructed from the response payload

If additional computed values are needed for explanation, they should be included explicitly in the response payload rather than only implied in prose

### 7.5 LLM-Digestible Outputs

Tool results should not be just raw row dumps.

Default tool response shape should include:

- `summary`
- `highlights`
- `data`
- `metadata`

Intent:

- `summary` gives the model the main conclusion quickly
- `highlights` provides a small set of ready-to-use observations
- `data` preserves structured details
- `metadata` communicates freshness and pipeline context

### 7.6 Resources Before Tools

Resources should help the model learn:

- what data exists
- what regions and energy sources are valid
- what date range is available
- what the current freshness and pipeline state are

Tools should answer parameterized questions.

Resources should provide stable context.

---

## 8. Common Response Envelope

Recommended tool response shape:

```json
{
  "summary": {
    "question": "Load trend for ERCOT from 2026-03-20 to 2026-03-28",
    "time_range": {
      "start_date": "2026-03-20",
      "end_date": "2026-03-28"
    },
    "region_scope": ["ERCOT"],
    "row_count": 9,
    "main_takeaway": "Load was broadly stable with a peak on 2026-03-27."
  },
  "highlights": [
    "Peak load occurred on 2026-03-27.",
    "Freshness is stale because data freshness is stale."
  ],
  "data": [],
  "metadata": {
    "data_as_of": "2026-03-28T09:30:00Z",
    "pipeline_run_id": "scheduled__2026-03-28T10:00:00+00:00",
    "freshness_status": "stale",
    "source_tables": ["marts.agg_load_daily", "meta.freshness_log", "meta.pipeline_state"],
    "result_truncated": false
  }
}
```

Recommended error shape:

```json
{
  "error": {
    "code": "validation_error",
    "message": "start_date must be less than or equal to end_date",
    "hint": "Choose a date range where start_date <= end_date."
  }
}
```

The metadata fields should preserve REST semantics for:

- `data_as_of`
- `pipeline_run_id`
- `freshness_status`

Additional MCP metadata fields are recommended:

- `source_tables`
- `result_truncated`
- optional `row_limit_applied`

Error-class alignment rule:

- REST and MCP should use the same business error categories such as validation errors or repository failures
- the outer error envelope does not need to match REST exactly
- `hint` is an MCP-specific optional enhancement field

### 8.1 Empty Results

If parameters are valid but no matching records exist, the tool should return a successful response with:

- empty `data`
- `result_truncated = false`
- a deterministic `summary.main_takeaway` such as "No records found for the requested filters."

This should not be treated as `not_found` unless the request refers to a structurally invalid object rather than a valid filter producing no rows.

### 8.2 Time Semantics

Unless otherwise specified:

- `start_date` and `end_date` are closed-interval filters over `observation_date`
- timestamps are returned in ISO 8601 format
- timestamps should be normalized to UTC
- hourly load queries may return `observation_timestamp`, but filtering still follows `observation_date`

This avoids accidental interpretation of tools as arbitrary timestamp-range queries.

### 8.3 Result Limits and Truncation

The MCP layer needs stricter result-size controls than REST because responses are consumed by agents.

Recommended default limits:

- `get_load_trends`: maximum 500 rows; additionally cap `hourly` requests to 7 days
- `get_generation_mix`: maximum 500 rows
- `get_top_demand_regions`: maximum 500 rows total response size
- `get_anomalies`: maximum 200 rows

Not all tools should handle oversize requests the same way.

Validation-first tools:

- `get_load_trends`
- `get_generation_mix`
- `get_top_demand_regions`

For these tools:

- if the requested shape is too large or semantically unsafe for truncation, return an error rather than silently clipping the requested time range
- for `get_load_trends(time_granularity = hourly)`, if the requested date span exceeds `hourly_max_days`, return `validation_error` with a hint to use `daily` or shorten the range
- for `get_generation_mix` and `get_top_demand_regions`, prefer `validation_error` when an explicit date range is too broad to return faithfully within documented row limits

Truncation-friendly tools:

- `get_anomalies`

For these tools:

- return a successful response
- truncate deterministically using the tool's documented ordering
- set `metadata.result_truncated = true`
- optionally include `metadata.row_limit_applied`
- mention truncation in `summary.main_takeaway` or a highlight

Tools should not silently return a partial dataset without indicating truncation.

### 8.4 Unsupported Capability Errors

Some requests may be well-formed but outside the capabilities of the serving design.

In v1, this category is intentionally forward-compatible. The current documented tool parameter shapes do not expose an explicit scope parameter for every unsupported analytical intent. That means some unsupported intents can be described at the agent or natural-language level without being directly expressible as a distinct v1 tool invocation.

Examples:

- asking for a whole-period cumulative leaderboard when the documented tool only returns per-day rankings
- asking for whole-period generation composition when the documented tool only defines per-day share
- asking for fuzzy region search or alias expansion when v1 only supports canonical region values plus exact region-name normalization

Recommended MCP-specific error category:

- `unsupported_capability`

Recommended behavior:

- use `unsupported_capability` when a well-formed request shape is understandable but not supported by the current serving model
- use `validation_error` when the request is malformed or violates a documented parameter rule
- include a `hint` pointing to the closest supported query shape or alternative tool

v1 clarification:

- keep `unsupported_capability` as a documented category for interface stability and future explicit shape parameters
- do not require every current v1 tool to have a directly triggerable `unsupported_capability` branch from its documented parameter set
- when a tool is invoked with valid v1 parameters, it should normally return the documented supported shape rather than infer a different unsupported intent that was only present in upstream natural language

---

## 9. Tools

### 9.1 `get_load_trends`

Use when:

- the user asks how load changed over time for a specific region
- the user asks for peaks, troughs, or trend direction in a region

Do not use when:

- the user wants top-demand ranking across regions
- the user mainly asks about freshness or pipeline health

Required inputs:

- `region`
- `start_date`
- `end_date`

Optional inputs:

- `time_granularity`: `daily` | `hourly`
- `include_summary_stats`: boolean, default `true`

Semantics:

- maps to the same business capability as REST load metrics
- `time_granularity` is an MCP adapter field name and may be translated to the serving layer's `granularity`
- date filtering is by `observation_date`, inclusive on both bounds
- if `time_granularity` is omitted, default to `daily`

Size and safety rules:

- daily estimated rows may be computed as `number_of_calendar_days_in_closed_interval`
- hourly estimated rows may be computed conservatively as `number_of_calendar_days_in_closed_interval × 24`
- `hourly` requests are capped at 7 calendar days
- if an `hourly` request exceeds that cap, return `validation_error`
- do not auto-shorten the requested range
- if a request would exceed the documented row budget, prefer `validation_error` over silent truncation

Result ordering:

- `daily`: `observation_date ASC`
- `hourly`: `observation_timestamp ASC`

Backed by:

- REST capability: `GET /metrics/load`

### 9.2 `get_generation_mix`

Use when:

- the user asks which energy sources dominate generation in a region
- the user asks how generation composition changes over time

Do not use when:

- the user wants total regional demand ranking
- the user is asking about freshness or pipeline state

Required inputs:

- `region`
- `start_date`
- `end_date`

Optional inputs:

- `include_percentages`: boolean, default `true`

Percentage rule:

- if `include_percentages = true`, percentages are computed within each `observation_date` and `region`
- these percentages represent per-day generation share, not whole-period cumulative share
- whole-period composition should not be implied unless a dedicated precomputed capability is added later
- when `include_percentages = true`, each returned row should include an explicit derived field such as `generation_share_pct`

Size and safety rules:

- estimated rows may be computed as `number_of_calendar_days_in_closed_interval × count(canonical energy_source values from marts.dim_energy_source)`
- if an explicit date range would exceed the documented row budget, prefer `validation_error` over silent truncation
- do not silently drop trailing dates from a requested time range

Result ordering:

- `observation_date ASC, energy_source ASC`

Backed by:

- REST capability: `GET /metrics/generation-mix`

### 9.3 `get_top_demand_regions`

Use when:

- the user asks which regions had the highest demand on each day in a date range
- the user wants per-day top-N regional ranking within a period

Do not use when:

- the user wants a single cumulative ranking across the whole period
- the user is focused on one specific region's trend

Required inputs:

- `start_date`
- `end_date`

Optional inputs:

- `top_n`

Semantics:

- returns the precomputed daily ranking for each `observation_date` in the requested range
- this is not a whole-period aggregate leaderboard
- `top_n` is an MCP adapter field name and may be translated to the serving layer's `limit`
- if `top_n` is omitted, default to `10`

Size and safety rules:

- estimated rows may be computed as `number_of_calendar_days_in_closed_interval × top_n`
- if the requested date range would exceed the documented row budget, prefer `validation_error` over silent truncation

Result ordering:

- `observation_date ASC, rank ASC`

Backed by:

- REST capability: `GET /metrics/top-regions`

### 9.4 `check_data_freshness`

Use when:

- the user asks if the data is current
- the agent wants to check data trustworthiness before answering an analytical question

Required inputs:

- none

Optional inputs:

- optional `include_explanation`: boolean, default `true`

Deterministic summary rule:

- `summary.main_takeaway` should be based on `freshness_status`, `data_as_of`, and, when available, the latest freshness check timestamp

Backed by:

- REST capability: `GET /freshness`

### 9.5 `get_anomalies`

Use when:

- the user asks whether there were unusual deviations
- the user asks for recent anomalies by date or region

Do not use when:

- the user only wants standard trend results

Required inputs:

- none

Optional inputs:

- `region` (optional)
- `start_date` (optional)
- `end_date` (optional)
- `anomaly_only`: boolean, default `true`

Semantics:

- input filtering should use anomaly-specific naming
- output rows should preserve the field name `anomaly_flag`
- if implementation chooses to accept `only_flagged` as an alias, `anomaly_only` should remain the canonical documented parameter

Suggested protections:

- deterministic ordering should follow the underlying serving behavior
- if no date filters are provided and the result set exceeds limits, truncate and mark the response accordingly

Result ordering:

- `observation_date DESC, checked_at DESC, region ASC, metric_name ASC`

Backed by:

- REST capability: `GET /anomalies`

### 9.6 `get_pipeline_status`

Use when:

- the user asks about the last successful run
- the agent needs to distinguish stale data from a stalled pipeline

Required inputs:

- none

Optional inputs:

- optional `include_interpretation`: boolean, default `true`

Deterministic summary rule:

- `summary.main_takeaway` should be based on the latest successful pipeline window and the most recent pipeline update timestamp

Backed by:

- REST capability: `GET /pipeline/status`

---

## 10. Resources

### 10.1 `schema://grid-metrics`

Purpose:

- top-level discovery resource for tools, supported metrics, date range, and time granularities

Suggested contents:

- available tools
- supported time granularities
- available date bounds
- supported metric concepts
- usage guidance
- default limits and defaults per tool
- canonical parameter names and adapter aliases where relevant
- result ordering per tool
- overflow behavior per tool

This resource should be machine-readable first and prose-friendly second.

Recommended shape:

```json
{
  "tools": {
    "get_load_trends": {
      "required_params": ["region", "start_date", "end_date"],
      "optional_params": ["time_granularity", "include_summary_stats"],
      "defaults": {"time_granularity": "daily", "include_summary_stats": true},
      "accepted_region_inputs": ["region", "region_name"],
      "limits": {"max_rows": 500, "hourly_max_days": 7},
      "derived_fields": [],
      "result_ordering": {
        "daily": "observation_date asc",
        "hourly": "observation_timestamp asc"
      },
      "overflow_behavior": {
        "hourly_too_wide": "validation_error",
        "other_oversize_request": "validation_error"
      }
    }
  }
}
```

Recommended additions for other tools:

- `get_generation_mix.derived_fields = ["generation_share_pct"]` when `include_percentages = true`
- each tool definition should expose accepted input forms, defaults, ordering, and overflow behavior in a machine-readable way

Date-bounds note:

- `available date bounds` may be derived by querying min/max `observation_date` across serving-safe aggregate tables
- this derivation should be explicit and documented rather than implied as a pre-existing metadata table

### 10.2 `status://data-quality`

Purpose:

- current operational context for analytical answers

Suggested contents:

- latest freshness state
- combined freshness status
- latest pipeline status
- anomaly summary
- last checked timestamps

Anomaly summary should be narrowly defined and cheap to compute.

Recommended fields:

- `latest_anomaly_checked_at`
- `flagged_anomaly_count_last_7_days`
- `affected_regions_last_7_days`

These summary values may be derived from `meta.anomaly_results` using lightweight counts over a documented recent window.

Anchor rule:

- the recent anomaly summary window should be anchored to the latest available `observation_date` in `meta.anomaly_results`, not wall-clock now

### 10.3 `schema://regions`

Purpose:

- help the agent choose valid region values

Suggested contents:

- required: canonical region code
- required: display name
- optional: observed date bounds where relevant

Not currently provided in v1:

- aliases

Source-of-truth rule:

- aliases are out of scope for v1 unless the dimension schema is explicitly expanded beyond `region` and `region_name`
- aliases should not be invented or hardcoded casually inside the MCP adapter without an explicit maintained source

### 10.4 `schema://energy-sources`

Purpose:

- help the agent interpret generation mix outputs

Suggested contents:

- required: canonical energy source code

No richer semantic fields are guaranteed in v1.

Source-of-truth rule:

- display labels, descriptions, and categories are out of scope for v1 unless `marts.dim_energy_source` is explicitly expanded beyond `energy_source`

---

## 11. Tool and Resource Contracts

### 11.1 Stability

Tools and resources should be stable enough for agent use:

- names should not churn casually
- field names should remain consistent
- metadata semantics should remain consistent with REST

Parameter names may differ from REST if the MCP adapter translation layer is documented and semantics remain aligned.

### 11.2 Read-Only Contract

All tools are read-only.

No tool should:

- update BigQuery
- trigger Airflow
- alter GCS contents
- mutate cache state beyond normal in-memory memoization

### 11.3 Caching

Simple in-memory TTL caching is acceptable for:

- resource payloads
- repeated hot aggregate reads

Caching must not change result semantics.

### 11.4 Region Normalization

Region handling needs stronger rules for agent use than the current REST layer requires.

Recommended behavior:

- accept canonical region codes
- perform case-insensitive normalization
- optionally normalize surrounding whitespace before validation
- exact case-insensitive matching on `region_name` may be supported in addition to canonical `region`
- alias resolution is out of scope for v1 because the current dimension schema does not provide alias metadata
- if normalization fails, return `validation_error`
- when possible, include candidate region values in the error hint

Region normalization may be implemented inside the MCP adapter or shared service layer, but the externally visible behavior should be deterministic.

Optional future enhancement:

- a dedicated `resolve_region` helper tool could be added later if normalization through resources plus tool-side validation proves insufficient
- this is not required for the first MCP version if `schema://regions` and tool-side normalization cover the main agent workflows

---

## 12. Validation and Error Semantics

Core validation rules should stay aligned with the serving service layer.

MCP may add adapter-level safety behavior that REST does not currently expose directly, including:

- response-size guards
- truncation markers
- normalization behavior
- deterministic summary/highlight shaping

Examples:

- `start_date <= end_date`
- `region` must not be blank
- `top_n >= 1`
- `hourly` load range must not exceed the documented maximum window

Errors should be:

- structured
- deterministic
- safe for agent consumption

Recommended error categories:

- `validation_error` for malformed inputs or documented rule violations
- `unsupported_capability` as a reserved category for well-formed requests that exceed the supported analytical shape when such a shape is explicitly expressible in the interface
- `repository_error` when warehouse access fails

Examples of `unsupported_capability`:

- asking for fuzzy region search or approximate alias matching when v1 only supports canonical region plus exact region-name normalization

v1 note:

- current v1 tool schemas may not expose a direct parameter-level path to every unsupported analytical intent described in prose
- this category remains part of the interface contract so later MCP revisions can add explicit shape parameters without changing the error taxonomy

Do not return raw stack traces or warehouse-specific internals in tool errors.

---

## 13. Testing Scope

This document intentionally keeps MCP testing focused and narrow for the first implementation.

Required MCP-specific testing:

- tool registration and discovery
- parameter validation
- success response structure
- error response structure
- summary/highlights/data/metadata presence
- resource payload structure
- mapping correctness between MCP tools and shared serving logic
- result limit and truncation behavior
- empty-result behavior
- time-semantics behavior for date filtering
- region normalization behavior

Recommended examples:

- `get_load_trends` rejects invalid date ranges
- `get_load_trends(hourly)` enforces the documented maximum window
- `get_top_demand_regions` rejects invalid `top_n`
- `get_top_demand_regions` documents and returns per-day rankings rather than a whole-period leaderboard
- `check_data_freshness` returns `unknown` correctly when no freshness record exists
- `get_anomalies` defaults to flagged-only behavior
- `get_generation_mix(include_percentages=true)` computes per-day, per-region percentages only
- valid empty filters return success with empty `data`

Out of scope for this document:

- agent usability evaluation
- automated end-to-end prompt-loop testing
- remote transport testing

---

## 14. Suggested Repository Placement

Recommended directory:

```text
DOCS/MCP.md
mcp/
  app/
    adapters/
    config/
    resources/
    tools/
    main.py
  pyproject.toml
```

The `mcp/` package name should match the repository structure described in the spec.

---

## 15. Summary

VoltageHub should treat MCP as a first-class serving interface, not as a wrapper around HTTP endpoints.

The core design choice is:

- shared warehouse access and service semantics
- adapter-level parameter translation where useful
- different transport and output shaping for LLM use

If the implementation follows this document, the MCP server will remain:

- safe
- read-only
- predictable
- cheap to operate
- understandable to agents
