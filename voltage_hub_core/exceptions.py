from __future__ import annotations


class AppError(Exception):
    """Base application error with a stable business error code."""

    status_code = 500
    error_code = "internal_error"

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class ValidationAppError(AppError):
    status_code = 400
    error_code = "validation_error"


class NotFoundAppError(AppError):
    status_code = 404
    error_code = "not_found"


class RepositoryError(AppError):
    status_code = 503
    error_code = "repository_error"


class UnsupportedCapabilityError(AppError):
    status_code = 400
    error_code = "unsupported_capability"
