from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.schemas.metrics import (
    GenerationMixResponse,
    LoadGranularity,
    LoadMetricsResponse,
    TopRegionsResponse,
)
from app.services.metrics import MetricsService, get_metrics_service

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/load", response_model=LoadMetricsResponse)
def get_load_metrics(
    service: Annotated[MetricsService, Depends(get_metrics_service)],
    region: str = Query(...),
    start_date: date = Query(...),
    end_date: date = Query(...),
    granularity: LoadGranularity = Query(...),
) -> LoadMetricsResponse:
    return service.get_load_metrics(
        region=region,
        start_date=start_date,
        end_date=end_date,
        granularity=granularity,
    )


@router.get("/generation-mix", response_model=GenerationMixResponse)
def get_generation_mix(
    service: Annotated[MetricsService, Depends(get_metrics_service)],
    region: str = Query(...),
    start_date: date = Query(...),
    end_date: date = Query(...),
) -> GenerationMixResponse:
    return service.get_generation_mix(
        region=region,
        start_date=start_date,
        end_date=end_date,
    )


@router.get("/top-regions", response_model=TopRegionsResponse)
def get_top_regions(
    service: Annotated[MetricsService, Depends(get_metrics_service)],
    start_date: date = Query(...),
    end_date: date = Query(...),
    limit: int = Query(default=10, ge=1),
) -> TopRegionsResponse:
    return service.get_top_regions(
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )
