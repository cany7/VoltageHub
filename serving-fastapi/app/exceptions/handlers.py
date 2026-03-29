from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.exceptions.base import AppError
from app.schemas.error import ErrorResponse

LOGGER = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(error=exc.error_code, detail=exc.message).model_dump(),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation_error(
        _: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content=ErrorResponse(
                error="validation_error",
                detail=str(exc),
            ).model_dump(),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = str(exc.detail) if exc.detail else "HTTP error"
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(error="http_error", detail=detail).model_dump(),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        LOGGER.exception("Unhandled serving API error", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error="internal_error",
                detail="Internal server error",
            ).model_dump(),
        )
