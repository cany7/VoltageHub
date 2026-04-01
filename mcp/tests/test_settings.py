from __future__ import annotations

from pathlib import Path

from app.config import settings as settings_module


def test_mcp_settings_reads_mcp_specific_env_vars(monkeypatch, tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "MCP_GCP_PROJECT_ID=mcp-project",
                "MCP_GOOGLE_APPLICATION_CREDENTIALS=/abs/path/service-account.json",
                "BQ_DATASET_MARTS=marts_alt",
                "BQ_DATASET_META=meta_alt",
            ]
        ),
        encoding="utf-8",
    )

    for key in (
        "MCP_GCP_PROJECT_ID",
        "MCP_GOOGLE_APPLICATION_CREDENTIALS",
        "BQ_DATASET_MARTS",
        "BQ_DATASET_META",
    ):
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setattr(settings_module, "_project_env_path", lambda: env_path)
    settings_module.get_mcp_settings.cache_clear()
    settings = settings_module.get_mcp_settings()

    assert settings.gcp_project_id == "mcp-project"
    assert settings.google_application_credentials == "/abs/path/service-account.json"
    assert settings.bq_dataset_marts == "marts_alt"
    assert settings.bq_dataset_meta == "meta_alt"

    settings_module.get_mcp_settings.cache_clear()
