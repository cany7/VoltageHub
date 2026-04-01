from __future__ import annotations

import os
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FreshnessStatus = Literal["fresh", "stale", "unknown"]
LoadGranularity = Literal["hourly", "daily"]


class AppSettings(BaseModel):
    """Environment-backed runtime settings shared by serving interfaces."""

    model_config = ConfigDict(frozen=True)

    gcp_project_id: str = Field(alias="GCP_PROJECT_ID")
    bq_dataset_marts: str = Field(default="marts", alias="BQ_DATASET_MARTS")
    bq_dataset_meta: str = Field(default="meta", alias="BQ_DATASET_META")
    port: int = Field(default=8090, alias="PORT")
    cache_ttl_seconds: int = Field(default=300, alias="CACHE_TTL_SECONDS")
    google_application_credentials: str | None = Field(
        default=None,
        alias="GOOGLE_APPLICATION_CREDENTIALS",
    )


def _project_env_path() -> Path:
    cwd = Path.cwd().resolve()
    for candidate_root in (cwd, *cwd.parents):
        candidate = candidate_root / ".env"
        if candidate.exists():
            return candidate
    return Path(__file__).resolve().parents[1] / ".env"


def _load_dotenv_defaults() -> dict[str, str]:
    values: dict[str, str] = {}
    env_path = _project_env_path()
    if not env_path.exists():
        return values

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        values[key] = value.strip().strip("'\"")

    return values


def _settings_source() -> dict[str, str]:
    return {
        **_load_dotenv_defaults(),
        **os.environ,
    }


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    return AppSettings.model_validate(_settings_source())


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


class RegionRecord(BaseModel):
    region: str
    region_name: str


class EnergySourceRecord(BaseModel):
    energy_source: str
