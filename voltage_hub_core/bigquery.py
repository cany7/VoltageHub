from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from google.cloud import bigquery
from google.oauth2 import service_account

from voltage_hub_core.schemas import AppSettings, get_settings


@lru_cache(maxsize=4)
def get_bigquery_client(settings: AppSettings | None = None) -> bigquery.Client:
    runtime_settings = settings or get_settings()
    credentials_path = runtime_settings.google_application_credentials
    if credentials_path:
        credentials_file = Path(credentials_path).expanduser()
        credentials = service_account.Credentials.from_service_account_file(
            credentials_file
        )
        return bigquery.Client(
            project=runtime_settings.gcp_project_id,
            credentials=credentials,
        )
    return bigquery.Client(project=runtime_settings.gcp_project_id)
