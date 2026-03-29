from __future__ import annotations

from fastapi import APIRouter

from app.health.service import get_health
from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return get_health()
