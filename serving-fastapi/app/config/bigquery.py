from __future__ import annotations

from fastapi import Depends
from google.cloud import bigquery

from app.config.settings import AppSettings, get_settings


def get_bigquery_client(
    settings: AppSettings = Depends(get_settings),
) -> bigquery.Client:
    """Build a BigQuery client using Application Default Credentials."""

    return bigquery.Client(project=settings.gcp_project_id)
