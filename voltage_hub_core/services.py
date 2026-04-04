from __future__ import annotations

from datetime import date

from voltage_hub_core.cache import QueryCache
from voltage_hub_core.exceptions import ValidationAppError
from voltage_hub_core.repositories import (
    ControlPlaneRepository,
    DimensionRepository,
    MetricsRepository,
)
from voltage_hub_core.schemas import (
    AnomalyRecord,
    EnergySourceRecord,
    FreshnessResponse,
    FreshnessStatus,
    GenerationMixRecord,
    GenerationMixResponse,
    LoadGranularity,
    LoadMetricDailyRecord,
    LoadMetricHourlyRecord,
    LoadMetricsResponse,
    PipelineStatusResponse,
    RegionRecord,
    ResponseMetadata,
    TopRegionsRecord,
    TopRegionsResponse,
)


class MetricsService:
    def __init__(self, repository: MetricsRepository, cache: QueryCache) -> None:
        self.repository = repository
        self.cache = cache

    def get_load_metrics(
        self,
        *,
        region: str,
        start_date: date,
        end_date: date,
        granularity: LoadGranularity,
    ) -> LoadMetricsResponse:
        _validate_region(region)
        _validate_date_range(start_date, end_date)

        rows = self.cache.get_or_set(
            ("metrics.load", region, start_date.isoformat(), end_date.isoformat(), granularity),
            lambda: self.repository.list_load_metrics(
                region=region,
                start_date=start_date,
                end_date=end_date,
                granularity=granularity,
            ),
        )
        if granularity == "hourly":
            data = [LoadMetricHourlyRecord(**row) for row in rows]
        else:
            data = [LoadMetricDailyRecord(**row) for row in rows]

        return LoadMetricsResponse(data=data, metadata=self._build_metadata())

    def get_generation_mix(
        self,
        *,
        region: str,
        start_date: date,
        end_date: date,
    ) -> GenerationMixResponse:
        _validate_region(region)
        _validate_date_range(start_date, end_date)

        rows = self.cache.get_or_set(
            ("metrics.generation_mix", region, start_date.isoformat(), end_date.isoformat()),
            lambda: self.repository.list_generation_mix(
                region=region,
                start_date=start_date,
                end_date=end_date,
            ),
        )
        data = [GenerationMixRecord(**row) for row in rows]
        return GenerationMixResponse(data=data, metadata=self._build_metadata())

    def get_top_regions(
        self,
        *,
        start_date: date,
        end_date: date,
        limit: int,
    ) -> TopRegionsResponse:
        _validate_date_range(start_date, end_date)
        if limit < 1:
            raise ValidationAppError("limit must be greater than or equal to 1")

        rows = self.cache.get_or_set(
            ("metrics.top_regions", start_date.isoformat(), end_date.isoformat(), limit),
            lambda: self.repository.list_top_regions(
                start_date=start_date,
                end_date=end_date,
                limit=limit,
            ),
        )
        data = [TopRegionsRecord(**row) for row in rows]
        return TopRegionsResponse(data=data, metadata=self._build_metadata())

    def get_available_date_bounds(self) -> dict[str, date | None]:
        return self.cache.get_or_set(
            ("metrics.date_bounds",),
            self.repository.get_available_date_bounds,
        )

    def _build_metadata(self) -> ResponseMetadata:
        metadata = self.cache.get_or_set(
            ("metrics.response_metadata",),
            self.repository.get_response_metadata,
        )
        if metadata is None:
            return ResponseMetadata(
                data_as_of=None,
                pipeline_run_id=None,
                freshness_status="unknown",
            )

        freshness_record = metadata.get("freshness") or {}
        pipeline_record = metadata.get("pipeline") or {}
        pipeline_status = freshness_record.get("pipeline_freshness_status", "unknown")
        data_status = freshness_record.get("data_freshness_status", "unknown")
        return ResponseMetadata(
            data_as_of=freshness_record.get("data_freshness_timestamp"),
            pipeline_run_id=pipeline_record.get("last_successful_run_id"),
            freshness_status=combine_freshness_status(pipeline_status, data_status),
        )


class ControlPlaneService:
    def __init__(self, repository: ControlPlaneRepository) -> None:
        self.repository = repository

    def get_freshness(self) -> FreshnessResponse:
        record = self.repository.get_latest_freshness()
        if record is None:
            return FreshnessResponse(
                pipeline_freshness_timestamp=None,
                data_freshness_timestamp=None,
                pipeline_freshness_status="unknown",
                data_freshness_status="unknown",
                freshness_status="unknown",
                checked_at=None,
            )

        pipeline_status = _normalize_status(record.get("pipeline_freshness_status"))
        data_status = _normalize_status(record.get("data_freshness_status"))
        return FreshnessResponse(
            pipeline_freshness_timestamp=record.get("pipeline_freshness_timestamp"),
            data_freshness_timestamp=record.get("data_freshness_timestamp"),
            pipeline_freshness_status=pipeline_status,
            data_freshness_status=data_status,
            freshness_status=combine_freshness_status(pipeline_status, data_status),
            checked_at=record.get("checked_at"),
        )

    def get_pipeline_status(self) -> PipelineStatusResponse:
        record = self.repository.get_latest_pipeline_status()
        if record is None:
            return PipelineStatusResponse(
                pipeline_name=None,
                last_successful_window_start=None,
                last_successful_window_end=None,
                last_successful_run_id=None,
                updated_at=None,
            )

        return PipelineStatusResponse(**record)

    def get_anomalies(
        self,
        *,
        region: str | None,
        start_date: date | None,
        end_date: date | None,
        anomaly_only: bool,
    ) -> list[AnomalyRecord]:
        if start_date and end_date and start_date > end_date:
            raise ValidationAppError("start_date must be less than or equal to end_date")

        rows = self.repository.list_anomalies(
            region=region,
            start_date=start_date,
            end_date=end_date,
            anomaly_only=anomaly_only,
        )
        return [AnomalyRecord(**row) for row in rows]

    def get_anomaly_summary(self) -> dict[str, object]:
        return self.repository.get_anomaly_summary()


class SchemaService:
    def __init__(self, repository: DimensionRepository, cache: QueryCache) -> None:
        self.repository = repository
        self.cache = cache

    def list_regions(self) -> list[RegionRecord]:
        rows = self.cache.get_or_set(("schema.regions",), self.repository.list_regions)
        return [RegionRecord(**row) for row in rows]

    def list_energy_sources(self) -> list[EnergySourceRecord]:
        rows = self.cache.get_or_set(
            ("schema.energy_sources",),
            self.repository.list_energy_sources,
        )
        return [EnergySourceRecord(**row) for row in rows]


def combine_freshness_status(
    pipeline_status: FreshnessStatus,
    data_status: FreshnessStatus,
) -> FreshnessStatus:
    if "stale" in {pipeline_status, data_status}:
        return "stale"
    if pipeline_status == "fresh" and data_status == "fresh":
        return "fresh"
    return "unknown"


def _normalize_status(value: str | None) -> FreshnessStatus:
    if value in {"fresh", "stale", "unknown"}:
        return value
    return "unknown"


def _validate_date_range(start_date: date, end_date: date) -> None:
    if start_date > end_date:
        raise ValidationAppError("start_date must be less than or equal to end_date")


def _validate_region(region: str) -> None:
    if not region.strip():
        raise ValidationAppError("region must not be empty")
