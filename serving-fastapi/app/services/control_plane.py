from __future__ import annotations

from datetime import date

from fastapi import Depends

from app.exceptions.base import ValidationAppError
from app.repositories.control_plane import (
    ControlPlaneRepository,
    get_control_plane_repository,
)
from app.schemas.control_plane import (
    AnomalyRecord,
    FreshnessResponse,
    PipelineStatusResponse,
)
from app.schemas.common import FreshnessStatus


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


def get_control_plane_service(
    repository: ControlPlaneRepository = Depends(get_control_plane_repository),
) -> ControlPlaneService:
    return ControlPlaneService(repository=repository)
