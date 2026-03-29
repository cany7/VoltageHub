from __future__ import annotations

import os
from functools import lru_cache

from pydantic import BaseModel, ConfigDict, Field


class AppSettings(BaseModel):
    """Environment-backed runtime settings for the serving API."""

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


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    return AppSettings.model_validate(os.environ)
