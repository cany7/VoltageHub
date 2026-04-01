from fastapi import Depends
from google.cloud import bigquery

from app.config.settings import AppSettings, get_settings
from voltage_hub_core.bigquery import get_bigquery_client as build_bigquery_client


def get_bigquery_client(
    settings: AppSettings = Depends(get_settings),
) -> bigquery.Client:
    return build_bigquery_client(settings)


__all__ = ["get_bigquery_client"]
