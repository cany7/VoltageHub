from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable

from pydantic import BaseModel

from app.config.runtime import Runtime
from voltage_hub_core.exceptions import (
    AppError,
    ValidationAppError,
)
from voltage_hub_core.schemas import (
    AnomalyRecord,
    GenerationMixRecord,
    FreshnessResponse,
    LoadMetricDailyRecord,
    LoadMetricHourlyRecord,
    PipelineStatusResponse,
    TopRegionsRecord,
)

LOAD_MAX_ROWS = 500
GENERATION_MIX_MAX_ROWS = 500
TOP_REGIONS_MAX_ROWS = 500
ANOMALIES_MAX_ROWS = 200
HOURLY_MAX_DAYS = 7


@dataclass(frozen=True)
class RegisteredTool:
    name: str
    description: str
    handler: Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class RegisteredResource:
    uri: str
    name: str
    description: str
    handler: Callable[[], dict[str, Any]]


class VoltageHubMCPAdapter:
    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime

    def get_load_trends(
        self,
        *,
        region: str,
        start_date: date,
        end_date: date,
        time_granularity: str = "daily",
        include_summary_stats: bool = True,
    ) -> dict[str, Any]:
        try:
            canonical_region, region_name = self._normalize_region(region)
            day_count = _closed_interval_days(start_date, end_date)
            if time_granularity == "hourly":
                if day_count > HOURLY_MAX_DAYS:
                    raise ValidationAppError(
                        "hourly load requests cannot exceed 7 calendar days",
                        hint="Use daily granularity or shorten the requested date range.",
                    )
                estimated_rows = day_count * 24
            elif time_granularity == "daily":
                estimated_rows = day_count
            else:
                raise ValidationAppError(
                    "time_granularity must be one of: daily, hourly",
                    hint="Use either daily or hourly.",
                )

            if estimated_rows > LOAD_MAX_ROWS:
                raise ValidationAppError(
                    "requested load trend range exceeds the MCP row budget",
                    hint="Shorten the date range or use daily granularity.",
                )

            response = self.runtime.metrics_service.get_load_metrics(
                region=canonical_region,
                start_date=start_date,
                end_date=end_date,
                granularity=time_granularity,
            )
            data = [self._dump_model(row) for row in response.data]
            summary_stats = self._summarize_load_rows(response.data) if include_summary_stats else None
            return self._success_envelope(
                question=f"Load trend for {region_name} from {start_date} to {end_date}",
                start_date=start_date,
                end_date=end_date,
                region_scope=[canonical_region],
                data=data,
                metadata=response.metadata,
                source_tables=[
                    f"marts.agg_load_{time_granularity}",
                    "meta.freshness_log",
                    "meta.pipeline_state",
                ],
                main_takeaway=self._load_takeaway(response.data, region_name),
                highlights=self._load_highlights(response.data, response.metadata.freshness_status),
                extra_summary={"summary_stats": summary_stats} if summary_stats else None,
            )
        except AppError as exc:
            return self._error_envelope(exc)

    def get_generation_mix(
        self,
        *,
        region: str,
        start_date: date,
        end_date: date,
        include_percentages: bool = True,
    ) -> dict[str, Any]:
        try:
            canonical_region, region_name = self._normalize_region(region)
            energy_source_count = len(self.runtime.schema_service.list_energy_sources())
            estimated_rows = _closed_interval_days(start_date, end_date) * max(energy_source_count, 1)
            if estimated_rows > GENERATION_MIX_MAX_ROWS:
                raise ValidationAppError(
                    "requested generation-mix range exceeds the MCP row budget",
                    hint="Shorten the date range for generation mix results.",
                )

            response = self.runtime.metrics_service.get_generation_mix(
                region=canonical_region,
                start_date=start_date,
                end_date=end_date,
            )
            rows = list(response.data)
            totals_by_day: dict[str, float] = defaultdict(float)
            for row in rows:
                totals_by_day[row.observation_date.isoformat()] += row.daily_total_generation

            data = []
            for row in rows:
                payload = self._dump_model(row)
                if include_percentages:
                    total = totals_by_day[row.observation_date.isoformat()]
                    payload["generation_share_pct"] = 0.0 if total == 0 else round(
                        (row.daily_total_generation / total) * 100,
                        2,
                    )
                data.append(payload)

            return self._success_envelope(
                question=f"Generation mix for {region_name} from {start_date} to {end_date}",
                start_date=start_date,
                end_date=end_date,
                region_scope=[canonical_region],
                data=data,
                metadata=response.metadata,
                source_tables=[
                    "marts.agg_generation_mix",
                    "meta.freshness_log",
                    "meta.pipeline_state",
                ],
                main_takeaway=self._generation_takeaway(rows, region_name),
                highlights=self._generation_highlights(rows, include_percentages),
            )
        except AppError as exc:
            return self._error_envelope(exc)

    def get_top_demand_regions(
        self,
        *,
        start_date: date,
        end_date: date,
        top_n: int = 10,
    ) -> dict[str, Any]:
        try:
            if top_n < 1:
                raise ValidationAppError("top_n must be greater than or equal to 1")

            estimated_rows = _closed_interval_days(start_date, end_date) * top_n
            if estimated_rows > TOP_REGIONS_MAX_ROWS:
                raise ValidationAppError(
                    "requested top-demand range exceeds the MCP row budget",
                    hint="Shorten the date range or lower top_n.",
                )

            response = self.runtime.metrics_service.get_top_regions(
                start_date=start_date,
                end_date=end_date,
                limit=top_n,
            )
            rows = list(response.data)
            return self._success_envelope(
                question=f"Top demand regions from {start_date} to {end_date}",
                start_date=start_date,
                end_date=end_date,
                region_scope=[],
                data=[self._dump_model(row) for row in rows],
                metadata=response.metadata,
                source_tables=[
                    "marts.agg_top_regions",
                    "meta.freshness_log",
                    "meta.pipeline_state",
                ],
                main_takeaway=self._top_regions_takeaway(rows),
                highlights=self._top_regions_highlights(rows),
            )
        except AppError as exc:
            return self._error_envelope(exc)

    def check_data_freshness(self, *, include_explanation: bool = True) -> dict[str, Any]:
        try:
            response = self.runtime.control_plane_service.get_freshness()
            data = self._dump_model(response)
            highlights = []
            if include_explanation:
                highlights = [
                    f"Pipeline freshness is {response.pipeline_freshness_status}.",
                    f"Data freshness is {response.data_freshness_status}.",
                ]
            return self._success_envelope(
                question="Current data freshness status",
                start_date=None,
                end_date=None,
                region_scope=[],
                data=data,
                metadata={
                    "data_as_of": response.data_freshness_timestamp,
                    "pipeline_run_id": None,
                    "freshness_status": response.freshness_status,
                },
                source_tables=["meta.freshness_log"],
                main_takeaway=self._freshness_takeaway(response),
                highlights=highlights,
            )
        except AppError as exc:
            return self._error_envelope(exc)

    def get_anomalies(
        self,
        *,
        region: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        anomaly_only: bool = True,
    ) -> dict[str, Any]:
        try:
            normalized_region = None
            region_scope: list[str] = []
            if region is not None:
                normalized_region, _ = self._normalize_region(region)
                region_scope = [normalized_region]

            rows = self.runtime.control_plane_service.get_anomalies(
                region=normalized_region,
                start_date=start_date,
                end_date=end_date,
                anomaly_only=anomaly_only,
            )
            truncated = len(rows) > ANOMALIES_MAX_ROWS
            trimmed_rows = rows[:ANOMALIES_MAX_ROWS]
            highlights = self._anomaly_highlights(trimmed_rows, truncated)
            return self._success_envelope(
                question="Recent anomalies",
                start_date=start_date,
                end_date=end_date,
                region_scope=region_scope,
                data=[self._dump_model(row) for row in trimmed_rows],
                metadata=self._metadata_dict(
                    data_as_of=trimmed_rows[0].checked_at if trimmed_rows else None,
                    pipeline_run_id=None,
                    freshness_status="unknown",
                    source_tables=["meta.anomaly_results"],
                    result_truncated=truncated,
                    row_limit_applied=ANOMALIES_MAX_ROWS if truncated else None,
                ),
                source_tables=["meta.anomaly_results"],
                main_takeaway=self._anomaly_takeaway(trimmed_rows, truncated),
                highlights=highlights,
                row_limit_applied=ANOMALIES_MAX_ROWS if truncated else None,
                result_truncated=truncated,
            )
        except AppError as exc:
            return self._error_envelope(exc)

    def get_pipeline_status(
        self,
        *,
        include_interpretation: bool = True,
    ) -> dict[str, Any]:
        try:
            response = self.runtime.control_plane_service.get_pipeline_status()
            data = self._dump_model(response)
            highlights = []
            if include_interpretation and response.updated_at is not None:
                highlights.append(
                    f"Latest successful pipeline watermark was updated at {response.updated_at.isoformat()}."
                )
            return self._success_envelope(
                question="Latest successful pipeline status",
                start_date=None,
                end_date=None,
                region_scope=[],
                data=data,
                metadata={
                    "data_as_of": response.updated_at,
                    "pipeline_run_id": response.last_successful_run_id,
                    "freshness_status": "unknown",
                },
                source_tables=["meta.pipeline_state"],
                main_takeaway=self._pipeline_takeaway(response),
                highlights=highlights,
            )
        except AppError as exc:
            return self._error_envelope(exc)

    def schema_grid_metrics(self) -> dict[str, Any]:
        try:
            bounds = self.runtime.metrics_service.get_available_date_bounds()
            return self._dump_value({
                "tools": {
                    "get_load_trends": {
                        "required_params": ["region", "start_date", "end_date"],
                        "optional_params": ["time_granularity", "include_summary_stats"],
                        "defaults": {"time_granularity": "daily", "include_summary_stats": True},
                        "accepted_region_inputs": ["region", "region_name"],
                        "limits": {"max_rows": LOAD_MAX_ROWS, "hourly_max_days": HOURLY_MAX_DAYS},
                        "derived_fields": [],
                        "result_ordering": {
                            "daily": "observation_date asc",
                            "hourly": "observation_timestamp asc",
                        },
                        "overflow_behavior": {
                            "hourly_too_wide": "validation_error",
                            "other_oversize_request": "validation_error",
                        },
                    },
                    "get_generation_mix": {
                        "required_params": ["region", "start_date", "end_date"],
                        "optional_params": ["include_percentages"],
                        "defaults": {"include_percentages": True},
                        "accepted_region_inputs": ["region", "region_name"],
                        "limits": {"max_rows": GENERATION_MIX_MAX_ROWS},
                        "derived_fields": ["generation_share_pct"],
                        "result_ordering": "observation_date asc, energy_source asc",
                        "overflow_behavior": {"other_oversize_request": "validation_error"},
                    },
                    "get_top_demand_regions": {
                        "required_params": ["start_date", "end_date"],
                        "optional_params": ["top_n"],
                        "defaults": {"top_n": 10},
                        "limits": {"max_rows": TOP_REGIONS_MAX_ROWS},
                        "derived_fields": [],
                        "result_ordering": "observation_date asc, rank asc",
                        "overflow_behavior": {
                            "other_oversize_request": "validation_error",
                            "whole_period_leaderboard": "unsupported_capability",
                        },
                    },
                    "check_data_freshness": {
                        "required_params": [],
                        "optional_params": ["include_explanation"],
                        "defaults": {"include_explanation": True},
                        "result_ordering": "single record",
                    },
                    "get_anomalies": {
                        "required_params": [],
                        "optional_params": ["region", "start_date", "end_date", "anomaly_only"],
                        "defaults": {"anomaly_only": True},
                        "limits": {"max_rows": ANOMALIES_MAX_ROWS},
                        "result_ordering": "observation_date desc, checked_at desc, region asc, metric_name asc",
                        "overflow_behavior": {"other_oversize_request": "truncate"},
                    },
                    "get_pipeline_status": {
                        "required_params": [],
                        "optional_params": ["include_interpretation"],
                        "defaults": {"include_interpretation": True},
                        "result_ordering": "single record",
                    },
                },
                "supported_time_granularities": ["daily", "hourly"],
                "supported_metric_concepts": [
                    "load trends",
                    "generation mix",
                    "top demand regions",
                    "data freshness",
                    "anomalies",
                    "pipeline status",
                ],
                "available_date_bounds": bounds,
                "usage_guidance": {
                    "resources_before_tools": True,
                    "region_aliases_supported": False,
                    "notes": [
                        "Use schema://regions before region-filtered tools when region normalization is uncertain.",
                        "Top demand regions are daily rankings, not whole-period leaderboards.",
                        "Generation percentages are per-day, per-region shares only.",
                    ],
                },
            })
        except AppError as exc:
            return self._error_envelope(exc)

    def status_data_quality(self) -> dict[str, Any]:
        try:
            freshness = self.runtime.control_plane_service.get_freshness()
            pipeline_status = self.runtime.control_plane_service.get_pipeline_status()
            anomaly_summary = self.runtime.control_plane_service.get_anomaly_summary()
            return self._dump_value({
                "freshness": self._dump_model(freshness),
                "pipeline_status": self._dump_model(pipeline_status),
                "anomaly_summary": anomaly_summary,
            })
        except AppError as exc:
            return self._error_envelope(exc)

    def schema_regions(self) -> dict[str, Any]:
        try:
            rows = self.runtime.schema_service.list_regions()
            return self._dump_value({"regions": [self._dump_model(row) for row in rows]})
        except AppError as exc:
            return self._error_envelope(exc)

    def schema_energy_sources(self) -> dict[str, Any]:
        try:
            rows = self.runtime.schema_service.list_energy_sources()
            return self._dump_value({"energy_sources": [self._dump_model(row) for row in rows]})
        except AppError as exc:
            return self._error_envelope(exc)

    def _normalize_region(self, raw_region: str) -> tuple[str, str]:
        candidate = raw_region.strip()
        if not candidate:
            raise ValidationAppError("region must not be empty")

        regions = self.runtime.schema_service.list_regions()
        by_code = {row.region.casefold(): row for row in regions}
        by_name = {row.region_name.casefold(): row for row in regions}
        normalized = by_code.get(candidate.casefold()) or by_name.get(candidate.casefold())
        if normalized is None:
            examples = [row.region for row in regions[:5]]
            raise ValidationAppError(
                f"unsupported region: {raw_region}",
                hint=f"Use a canonical region code or exact region_name. Examples: {', '.join(examples)}.",
            )
        return normalized.region, normalized.region_name

    def _success_envelope(
        self,
        *,
        question: str,
        start_date: date | None,
        end_date: date | None,
        region_scope: list[str],
        data: Any,
        metadata: Any,
        source_tables: list[str],
        main_takeaway: str,
        highlights: list[str],
        extra_summary: dict[str, Any] | None = None,
        result_truncated: bool = False,
        row_limit_applied: int | None = None,
    ) -> dict[str, Any]:
        normalized_metadata = metadata
        if isinstance(metadata, BaseModel):
            normalized_metadata = self._dump_model(metadata)
        metadata_payload = self._metadata_dict(
            data_as_of=normalized_metadata.get("data_as_of"),
            pipeline_run_id=normalized_metadata.get("pipeline_run_id"),
            freshness_status=normalized_metadata.get("freshness_status", "unknown"),
            source_tables=source_tables,
            result_truncated=result_truncated,
            row_limit_applied=row_limit_applied,
        )
        summary = {
            "question": question,
            "time_range": {"start_date": start_date, "end_date": end_date},
            "region_scope": region_scope,
            "row_count": len(data) if isinstance(data, list) else (0 if data is None else 1),
            "main_takeaway": main_takeaway,
        }
        if extra_summary:
            summary.update(extra_summary)
        return {
            "summary": self._dump_value(summary),
            "highlights": highlights[:3],
            "data": self._dump_value(data),
            "metadata": metadata_payload,
        }

    def _error_envelope(self, exc: AppError) -> dict[str, Any]:
        payload = {
            "error": {
                "code": exc.error_code,
                "message": exc.message,
            }
        }
        if exc.hint:
            payload["error"]["hint"] = exc.hint
        return payload

    def _metadata_dict(
        self,
        *,
        data_as_of: Any,
        pipeline_run_id: str | None,
        freshness_status: str,
        source_tables: list[str],
        result_truncated: bool,
        row_limit_applied: int | None = None,
    ) -> dict[str, Any]:
        payload = {
            "data_as_of": self._dump_value(data_as_of),
            "pipeline_run_id": pipeline_run_id,
            "freshness_status": freshness_status,
            "source_tables": source_tables,
            "result_truncated": result_truncated,
        }
        if row_limit_applied is not None:
            payload["row_limit_applied"] = row_limit_applied
        return payload

    def _dump_model(self, model: BaseModel) -> dict[str, Any]:
        return model.model_dump(mode="json")

    def _dump_value(self, value: Any) -> Any:
        if isinstance(value, BaseModel):
            return value.model_dump(mode="json")
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, list):
            return [self._dump_value(item) for item in value]
        if isinstance(value, dict):
            return {key: self._dump_value(item) for key, item in value.items()}
        return value

    def _summarize_load_rows(
        self,
        rows: list[LoadMetricHourlyRecord | LoadMetricDailyRecord],
    ) -> dict[str, Any] | None:
        if not rows:
            return None
        if isinstance(rows[0], LoadMetricHourlyRecord):
            loads = [row.hourly_load for row in rows]
            peak_row = max(rows, key=lambda row: row.hourly_load)
            return {
                "min_load": min(loads),
                "max_load": max(loads),
                "peak_timestamp": peak_row.observation_timestamp,
            }
        loads = [row.total_load for row in rows]
        peak_row = max(rows, key=lambda row: row.total_load)
        return {
            "min_total_load": min(loads),
            "max_total_load": max(loads),
            "peak_date": peak_row.observation_date,
        }

    def _load_takeaway(
        self,
        rows: list[LoadMetricHourlyRecord | LoadMetricDailyRecord],
        region_name: str,
    ) -> str:
        if not rows:
            return "No records found for the requested filters."
        if isinstance(rows[0], LoadMetricHourlyRecord):
            peak_row = max(rows, key=lambda row: row.hourly_load)
            return (
                f"{region_name} peaked at {peak_row.hourly_load:.2f} on "
                f"{peak_row.observation_timestamp.isoformat()}."
            )
        peak_row = max(rows, key=lambda row: row.total_load)
        return f"{region_name} reached its highest daily load on {peak_row.observation_date.isoformat()}."

    def _load_highlights(
        self,
        rows: list[LoadMetricHourlyRecord | LoadMetricDailyRecord],
        freshness_status: str,
    ) -> list[str]:
        if not rows:
            return ["No records matched the requested load filters."]
        if isinstance(rows[0], LoadMetricHourlyRecord):
            peak_row = max(rows, key=lambda row: row.hourly_load)
            return [
                f"Peak hourly load was {peak_row.hourly_load:.2f} on {peak_row.observation_timestamp.isoformat()}.",
                f"Freshness status is {freshness_status}.",
            ]
        peak_row = max(rows, key=lambda row: row.total_load)
        return [
            f"Peak daily total load occurred on {peak_row.observation_date.isoformat()}.",
            f"Freshness status is {freshness_status}.",
        ]

    def _generation_takeaway(
        self,
        rows: list[GenerationMixRecord],
        region_name: str,
    ) -> str:
        if not rows:
            return "No records found for the requested filters."
        by_source: dict[str, float] = defaultdict(float)
        for row in rows:
            by_source[row.energy_source] += row.daily_total_generation
        top_source, _ = max(by_source.items(), key=lambda item: item[1])
        return f"{top_source} contributed the largest generation total in {region_name} across the requested period."

    def _generation_highlights(
        self,
        rows: list[GenerationMixRecord],
        include_percentages: bool,
    ) -> list[str]:
        if not rows:
            return ["No records matched the requested generation-mix filters."]
        first_date = rows[0].observation_date.isoformat()
        highlights = [f"Results are ordered by date and energy source starting at {first_date}."]
        if include_percentages:
            highlights.append("generation_share_pct is computed within each day and region only.")
        return highlights

    def _top_regions_takeaway(self, rows: list[TopRegionsRecord]) -> str:
        if not rows:
            return "No records found for the requested filters."
        first_row = rows[0]
        return (
            f"{first_row.region_name} ranked #1 on {first_row.observation_date.isoformat()} "
            "for the first returned day."
        )

    def _top_regions_highlights(self, rows: list[TopRegionsRecord]) -> list[str]:
        if not rows:
            return ["No records matched the requested top-demand filters."]
        return [
            "These rankings are per-day only, not a whole-period leaderboard.",
            f"Returned {len(rows)} ranked rows ordered by observation_date and rank.",
        ]

    def _freshness_takeaway(self, response: FreshnessResponse) -> str:
        if response.freshness_status == "unknown":
            return "Freshness is unknown because no freshness record is available."
        return (
            f"Freshness is {response.freshness_status} based on data_as_of "
            f"{response.data_freshness_timestamp.isoformat() if response.data_freshness_timestamp else 'unknown'}."
        )

    def _anomaly_takeaway(self, rows: list[AnomalyRecord], truncated: bool) -> str:
        if not rows:
            return "No records found for the requested filters."
        flagged = sum(1 for row in rows if row.anomaly_flag)
        message = f"Returned {flagged} flagged anomalies across {len(rows)} rows."
        if truncated:
            return f"{message} Results were truncated to the MCP row limit."
        return message

    def _anomaly_highlights(self, rows: list[AnomalyRecord], truncated: bool) -> list[str]:
        if not rows:
            return ["No anomaly rows matched the requested filters."]
        highlights = [
            "Rows are ordered by observation_date desc, checked_at desc, region asc, metric_name asc.",
            f"Flagged rows in this response: {sum(1 for row in rows if row.anomaly_flag)}.",
        ]
        if truncated:
            highlights.append("Results were truncated to the MCP anomaly row limit.")
        return highlights

    def _pipeline_takeaway(self, response: PipelineStatusResponse) -> str:
        if response.last_successful_run_id is None:
            return "No successful pipeline run has been recorded yet."
        return (
            f"The latest successful pipeline run is {response.last_successful_run_id}, "
            f"covering {response.last_successful_window_start} to {response.last_successful_window_end}."
        )


def tool_specs(adapter: VoltageHubMCPAdapter) -> list[RegisteredTool]:
    return [
        RegisteredTool(
            name="get_load_trends",
            description=(
                "Use this when the user wants load trends for a specific region over time. "
                "Do not use it for top-N regional ranking or freshness questions."
            ),
            handler=adapter.get_load_trends,
        ),
        RegisteredTool(
            name="get_generation_mix",
            description=(
                "Use this when the user asks which energy sources dominate generation in a region "
                "or how the generation mix changes over time. Do not use it for whole-period "
                "regional demand ranking."
            ),
            handler=adapter.get_generation_mix,
        ),
        RegisteredTool(
            name="get_top_demand_regions",
            description=(
                "Use this for per-day top-demand region rankings across a date range. "
                "Do not use it for a single cumulative leaderboard for the whole period."
            ),
            handler=adapter.get_top_demand_regions,
        ),
        RegisteredTool(
            name="check_data_freshness",
            description=(
                "Use this when the user asks whether the data is current or when you need to "
                "check trustworthiness before analysis."
            ),
            handler=adapter.check_data_freshness,
        ),
        RegisteredTool(
            name="get_anomalies",
            description=(
                "Use this when the user asks about unusual deviations or recent anomalies by "
                "date or region. Do not use it for normal trend analysis."
            ),
            handler=adapter.get_anomalies,
        ),
        RegisteredTool(
            name="get_pipeline_status",
            description=(
                "Use this when the user asks about the latest successful pipeline run or when "
                "you need to distinguish stale data from a stalled pipeline."
            ),
            handler=adapter.get_pipeline_status,
        ),
    ]


def resource_specs(adapter: VoltageHubMCPAdapter) -> list[RegisteredResource]:
    return [
        RegisteredResource(
            uri="schema://grid-metrics",
            name="schema_grid_metrics",
            description="Top-level discovery resource for tools, supported metrics, date bounds, and limits.",
            handler=adapter.schema_grid_metrics,
        ),
        RegisteredResource(
            uri="status://data-quality",
            name="status_data_quality",
            description="Current data quality context including freshness, pipeline status, and anomaly summary.",
            handler=adapter.status_data_quality,
        ),
        RegisteredResource(
            uri="schema://regions",
            name="schema_regions",
            description="Valid canonical regions and region_name values for MCP tools.",
            handler=adapter.schema_regions,
        ),
        RegisteredResource(
            uri="schema://energy-sources",
            name="schema_energy_sources",
            description="Canonical energy_source values used by generation-mix results.",
            handler=adapter.schema_energy_sources,
        ),
    ]


def _closed_interval_days(start_date: date, end_date: date) -> int:
    if start_date > end_date:
        raise ValidationAppError("start_date must be less than or equal to end_date")
    return (end_date - start_date).days + 1
