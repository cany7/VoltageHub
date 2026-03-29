from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SERVING_ROOT = PROJECT_ROOT / "serving-fastapi"
if str(SERVING_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVING_ROOT))

from app.config import settings as settings_module  # noqa: E402
from app.config.settings import AppSettings  # noqa: E402


def test_settings_read_expected_environment_fields(monkeypatch) -> None:
    monkeypatch.setenv("GCP_PROJECT_ID", "voltage-hub-dev")
    monkeypatch.setenv("BQ_DATASET_MARTS", "marts")
    monkeypatch.setenv("BQ_DATASET_META", "meta")
    monkeypatch.setenv("PORT", "8091")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/tmp/key.json")

    settings = AppSettings.model_validate(os.environ)

    assert settings.gcp_project_id == "voltage-hub-dev"
    assert settings.bq_dataset_marts == "marts"
    assert settings.bq_dataset_meta == "meta"
    assert settings.port == 8091
    assert settings.google_application_credentials == "/tmp/key.json"


def test_get_settings_falls_back_to_project_root_dotenv(monkeypatch, tmp_path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "GCP_PROJECT_ID=dotenv-project",
                "BQ_DATASET_MARTS=dotenv_marts",
                "BQ_DATASET_META=dotenv_meta",
                "PORT=8095",
            ]
        ),
        encoding="utf-8",
    )

    for key in (
        "GCP_PROJECT_ID",
        "BQ_DATASET_MARTS",
        "BQ_DATASET_META",
        "PORT",
        "GOOGLE_APPLICATION_CREDENTIALS",
    ):
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setattr(settings_module, "_project_env_path", lambda: env_path)
    settings_module.get_settings.cache_clear()

    settings = settings_module.get_settings()

    assert settings.gcp_project_id == "dotenv-project"
    assert settings.bq_dataset_marts == "dotenv_marts"
    assert settings.bq_dataset_meta == "dotenv_meta"
    assert settings.port == 8095


def test_get_settings_prefers_environment_over_project_root_dotenv(monkeypatch, tmp_path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "GCP_PROJECT_ID=dotenv-project",
                "BQ_DATASET_MARTS=dotenv_marts",
                "BQ_DATASET_META=dotenv_meta",
                "PORT=8095",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("GCP_PROJECT_ID", "env-project")
    monkeypatch.setenv("BQ_DATASET_MARTS", "env_marts")
    monkeypatch.setenv("PORT", "8099")
    monkeypatch.setattr(settings_module, "_project_env_path", lambda: env_path)
    settings_module.get_settings.cache_clear()

    settings = settings_module.get_settings()

    assert settings.gcp_project_id == "env-project"
    assert settings.bq_dataset_marts == "env_marts"
    assert settings.bq_dataset_meta == "dotenv_meta"
    assert settings.port == 8099
