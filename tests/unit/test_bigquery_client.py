from __future__ import annotations

from pathlib import Path

from voltage_hub_core.bigquery import get_bigquery_client
from voltage_hub_core.schemas import AppSettings


def test_get_bigquery_client_reuses_cached_client_for_same_settings(monkeypatch, tmp_path) -> None:
    credentials_path = tmp_path / "service-account.json"
    credentials_path.write_text("{}", encoding="utf-8")

    settings = AppSettings(
        GCP_PROJECT_ID="voltage-hub-dev",
        BQ_DATASET_MARTS="marts",
        BQ_DATASET_META="meta",
        GOOGLE_APPLICATION_CREDENTIALS=str(credentials_path),
    )

    class FakeCredentials:
        pass

    class FakeClient:
        def __init__(self, *, project: str, credentials: object) -> None:
            self.project = project
            self.credentials = credentials

    client_calls: list[tuple[str, object]] = []

    def fake_from_service_account_file(path: Path) -> FakeCredentials:
        assert path == credentials_path
        return FakeCredentials()

    def fake_client(*, project: str, credentials: object) -> FakeClient:
        client_calls.append((project, credentials))
        return FakeClient(project=project, credentials=credentials)

    get_bigquery_client.cache_clear()
    monkeypatch.setattr(
        "voltage_hub_core.bigquery.service_account.Credentials.from_service_account_file",
        fake_from_service_account_file,
    )
    monkeypatch.setattr("voltage_hub_core.bigquery.bigquery.Client", fake_client)

    first_client = get_bigquery_client(settings)
    second_client = get_bigquery_client(settings)

    assert first_client is second_client
    assert len(client_calls) == 1
