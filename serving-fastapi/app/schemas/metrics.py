from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.common import FreshnessStatus

LoadGranularity = Literal["hourly", "daily"]


class ResponseMetadata(BaseModel):
    data_as_of: datetime | None
    pipeline_run_id: str | None
    freshness_status: FreshnessStatus


class LoadMetricHourlyRecord(BaseModel):
    region: str
    region_name: str
    observation_timestamp: datetime
    observation_date: date
    hourly_load: float
    unit: str


class LoadMetricDailyRecord(BaseModel):
    region: str
    region_name: str
    observation_date: date
    avg_load: float
    min_load: float
    max_load: float
    total_load: float
    unit: str


class LoadMetricsResponse(BaseModel):
    data: list[LoadMetricHourlyRecord | LoadMetricDailyRecord]
    metadata: ResponseMetadata


class GenerationMixRecord(BaseModel):
    region: str
    region_name: str
    observation_date: date
    energy_source: str
    daily_total_generation: float
    unit: str


class GenerationMixResponse(BaseModel):
    data: list[GenerationMixRecord]
    metadata: ResponseMetadata


class TopRegionsRecord(BaseModel):
    observation_date: date
    region: str
    region_name: str
    daily_total_load: float
    rank: int


class TopRegionsResponse(BaseModel):
    data: list[TopRegionsRecord]
    metadata: ResponseMetadata
