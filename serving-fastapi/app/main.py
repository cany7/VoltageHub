from __future__ import annotations

from fastapi import FastAPI

from app.exceptions.handlers import register_exception_handlers
from app.middleware.request_logging import register_request_logging_middleware
from app.routers.control_plane import router as control_plane_router
from app.routers.health import router as health_router
from app.routers.metrics import router as metrics_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Voltage Hub Serving API",
        version="0.1.0",
        description="Read-only control-plane and aggregate serving endpoints for Voltage Hub.",
    )
    register_request_logging_middleware(app)
    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(control_plane_router)
    app.include_router(metrics_router)
    return app


app = create_app()
