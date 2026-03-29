from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

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


def _project_env_path() -> Path:
    return Path(__file__).resolve().parents[3] / ".env"


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
    # Assumption: local development should honor the repository-root `.env` file
    # as a fallback, while explicit process environment variables keep precedence.
    return {
        **_load_dotenv_defaults(),
        **os.environ,
    }


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    return AppSettings.model_validate(_settings_source())
