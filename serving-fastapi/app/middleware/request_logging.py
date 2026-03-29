from __future__ import annotations

import logging
import time
from uuid import uuid4

from fastapi import FastAPI, Request

LOGGER = logging.getLogger("voltage_hub.serving.requests")


def register_request_logging_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def log_request(request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("x-request-id") or str(uuid4())
        start = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000
            LOGGER.exception(
                "Serving request failed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "query": str(request.url.query),
                    "duration_ms": round(duration_ms, 2),
                    "client": request.client.host if request.client else None,
                },
            )
            raise

        duration_ms = (time.perf_counter() - start) * 1000
        response.headers["x-request-id"] = request_id
        LOGGER.info(
            "Serving request completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "query": str(request.url.query),
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
                "client": request.client.host if request.client else None,
            },
        )
        return response
