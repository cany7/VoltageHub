from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from voltage_hub_core.schemas import AppSettings


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
    return {
        **_load_dotenv_defaults(),
        **os.environ,
    }


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    return AppSettings.model_validate(_settings_source())


__all__ = ["AppSettings", "get_settings"]
