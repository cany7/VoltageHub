from __future__ import annotations

from datetime import date

from fastapi import Depends

from app.cache.query_cache import QueryCache, get_query_cache
from app.exceptions.base import ValidationAppError
from app.repositories.metrics import MetricsRepository, get_metrics_repository
from app.schemas.metrics import (
    GenerationMixRecord,
    GenerationMixResponse,
    LoadGranularity,
    LoadMetricDailyRecord,
    LoadMetricHourlyRecord,
    LoadMetricsResponse,
    ResponseMetadata,
    TopRegionsRecord,
    TopRegionsResponse,
)
from app.services.control_plane import combine_freshness_status


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

    def _build_metadata(self) -> ResponseMetadata:
        metadata = self.repository.get_response_metadata()
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


def _validate_date_range(start_date: date, end_date: date) -> None:
    if start_date > end_date:
        raise ValidationAppError("start_date must be less than or equal to end_date")


def _validate_region(region: str) -> None:
    if not region.strip():
        raise ValidationAppError("region must not be empty")


def get_metrics_service(
    repository: MetricsRepository = Depends(get_metrics_repository),
    cache: QueryCache = Depends(get_query_cache),
) -> MetricsService:
    return MetricsService(repository=repository, cache=cache)
