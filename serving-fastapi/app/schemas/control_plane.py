from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel

from app.schemas.common import FreshnessStatus


class FreshnessResponse(BaseModel):
    pipeline_freshness_timestamp: datetime | None
    data_freshness_timestamp: datetime | None
    pipeline_freshness_status: FreshnessStatus
    data_freshness_status: FreshnessStatus
    freshness_status: FreshnessStatus
    checked_at: datetime | None


class PipelineStatusResponse(BaseModel):
    pipeline_name: str | None
    last_successful_window_start: datetime | None
    last_successful_window_end: datetime | None
    last_successful_run_id: str | None
    updated_at: datetime | None


class AnomalyRecord(BaseModel):
    observation_date: date
    region: str
    metric_name: str
    current_value: float | None
    rolling_7d_avg: float | None
    pct_deviation: float | None
    anomaly_flag: bool
    checked_at: datetime | None
