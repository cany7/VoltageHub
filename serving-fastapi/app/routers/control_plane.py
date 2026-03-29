from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.schemas.control_plane import (
    AnomalyRecord,
    FreshnessResponse,
    PipelineStatusResponse,
)
from app.services.control_plane import ControlPlaneService, get_control_plane_service

router = APIRouter(tags=["control-plane"])


@router.get("/freshness", response_model=FreshnessResponse)
def get_freshness(
    service: Annotated[ControlPlaneService, Depends(get_control_plane_service)],
) -> FreshnessResponse:
    return service.get_freshness()


@router.get("/pipeline/status", response_model=PipelineStatusResponse)
def get_pipeline_status(
    service: Annotated[ControlPlaneService, Depends(get_control_plane_service)],
) -> PipelineStatusResponse:
    return service.get_pipeline_status()


@router.get("/anomalies", response_model=list[AnomalyRecord])
def get_anomalies(
    service: Annotated[ControlPlaneService, Depends(get_control_plane_service)],
    region: str | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    anomaly_only: bool = Query(default=True),
) -> list[AnomalyRecord]:
    return service.get_anomalies(
        region=region,
        start_date=start_date,
        end_date=end_date,
        anomaly_only=anomaly_only,
    )
