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
- reads only from precomputed `marts.agg_*` tables and `meta.*` tables
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

Recommended dependency direction:

```text
BigQuery repositories -> domain/services -> FastAPI REST adapters
BigQuery repositories -> domain/services -> MCP stdio adapters
```

Important rules:

- the MCP server should not call the REST API over HTTP
- the MCP server should not duplicate SQL already defined in serving repositories unless there is a deliberate new capability
- freshness semantics, metadata fields, and validation behavior should stay aligned with REST

This keeps REST and MCP contract-compatible at the business level even when their output envelopes differ.

---

## 5. Data Access Constraints

The MCP server is limited to the same serving-safe tables as the REST API.

Allowed tables:

- `marts.agg_load_hourly`
- `marts.agg_load_daily`
- `marts.agg_generation_mix`
- `marts.agg_top_regions`
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

Implications:

- no additional network port is required
- no HTTP authentication layer is needed in this design
- startup and operational model should stay simple

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
- `only_flagged`

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

### 7.3 LLM-Digestible Outputs

Tool results should not be just raw row dumps.

Default tool response shape should include:

- `summary`
- `highlights`
- `data`
- `metadata`

Intent:

- `summary` gives the model the main conclusion quickly
- `highlights` provides 2 to 5 ready-to-use observations
- `data` preserves structured details
- `metadata` communicates freshness and pipeline context

### 7.4 Resources Before Tools

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
    "freshness_status": "stale"
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

The metadata fields should preserve REST semantics:

- `data_as_of`
- `pipeline_run_id`
- `freshness_status`

---

## 9. Tools

### 9.1 `get_load_trends`

Use when:

- the user asks how load changed over time for a specific region
- the user asks for peaks, troughs, or trend direction in a region

Do not use when:

- the user wants top-demand ranking across regions
- the user mainly asks about freshness or pipeline health

Suggested inputs:

- `region`
- `start_date`
- `end_date`
- `time_granularity`: `daily` | `hourly`
- `include_summary_stats`: boolean, default `true`

Suggested protections:

- default to `daily`
- cap `hourly` range to a small window
- return a clear hint if the requested range is too large

Backed by:

- REST capability: `GET /metrics/load`

### 9.2 `get_generation_mix`

Use when:

- the user asks which energy sources dominate generation in a region
- the user asks how generation composition changes over time

Do not use when:

- the user wants total regional demand ranking
- the user is asking about freshness or pipeline state

Suggested inputs:

- `region`
- `start_date`
- `end_date`
- `include_percentages`: boolean, default `true`

Backed by:

- REST capability: `GET /metrics/generation-mix`

### 9.3 `get_top_demand_regions`

Use when:

- the user asks which regions had the highest demand
- the user wants a top-N regional ranking for a period

Do not use when:

- the user is focused on one specific region's trend

Suggested inputs:

- `start_date`
- `end_date`
- `top_n`

Backed by:

- REST capability: `GET /metrics/top-regions`

### 9.4 `check_data_freshness`

Use when:

- the user asks if the data is current
- the agent wants to check data trustworthiness before answering an analytical question

Suggested inputs:

- none
- optional `include_explanation`: boolean, default `true`

Backed by:

- REST capability: `GET /freshness`

### 9.5 `get_anomalies`

Use when:

- the user asks whether there were unusual deviations
- the user asks for recent anomalies by date or region

Do not use when:

- the user only wants standard trend results

Suggested inputs:

- `region` (optional)
- `start_date` (optional)
- `end_date` (optional)
- `only_flagged`: boolean, default `true`

Backed by:

- REST capability: `GET /anomalies`

### 9.6 `get_pipeline_status`

Use when:

- the user asks about the last successful run
- the agent needs to distinguish stale data from a stalled pipeline

Suggested inputs:

- none
- optional `include_interpretation`: boolean, default `true`

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

### 10.2 `status://data-quality`

Purpose:

- current operational context for analytical answers

Suggested contents:

- latest freshness state
- combined freshness status
- latest pipeline status
- anomaly summary
- last checked timestamps

### 10.3 `schema://regions`

Purpose:

- help the agent choose valid region values

Suggested contents:

- canonical region code
- display name
- common aliases
- available date bounds where relevant

### 10.4 `schema://energy-sources`

Purpose:

- help the agent interpret generation mix outputs

Suggested contents:

- canonical energy source code
- display label
- short description

---

## 11. Tool and Resource Contracts

### 11.1 Stability

Tools and resources should be stable enough for agent use:

- names should not churn casually
- field names should remain consistent
- metadata semantics should remain consistent with REST

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

---

## 12. Validation and Error Semantics

Validation rules should stay aligned with the serving service layer.

Examples:

- `start_date <= end_date`
- `region` must not be blank
- `top_n >= 1`

Errors should be:

- structured
- deterministic
- safe for agent consumption

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

Recommended examples:

- `get_load_trends` rejects invalid date ranges
- `get_top_demand_regions` rejects invalid `top_n`
- `check_data_freshness` returns `unknown` correctly when no freshness record exists
- `get_anomalies` defaults to flagged-only behavior

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
- different transport and output shaping for LLM use

If the implementation follows this document, the MCP server will remain:

- safe
- read-only
- predictable
- cheap to operate
- understandable to agents

