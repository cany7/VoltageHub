from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SERVING_ROOT = PROJECT_ROOT / "serving-fastapi"
if str(SERVING_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVING_ROOT))

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
