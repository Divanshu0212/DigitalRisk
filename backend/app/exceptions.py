"""Domain exceptions + FastAPI handlers producing the error envelope from
REQUIREMENTS §10.1:

    {
      "error": {
        "code": "VALIDATION_ERROR",
        "message": "...",
        "details": [ { "field": "...", "issue": "..." } ]
      }
    }

Centralising the envelope here means every failure path — validation, 404,
402, 429, 500 — returns an identical shape so the frontend can branch on
``error.code`` alone.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# Canonical error codes (REQUIREMENTS §10.2).
CODE_VALIDATION_ERROR = "VALIDATION_ERROR"
CODE_USER_NOT_FOUND = "USER_NOT_FOUND"
CODE_INVALID_CATEGORY = "INVALID_CATEGORY"
CODE_INVALID_UUID = "INVALID_UUID"
CODE_RATE_LIMITED = "RATE_LIMITED"
CODE_INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
CODE_INTERNAL_ERROR = "INTERNAL_ERROR"
CODE_SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


class AppError(Exception):
    """Base domain error carrying an HTTP status + canonical code."""

    code: str = CODE_INTERNAL_ERROR
    status_code: int = 500

    def __init__(
        self,
        message: str,
        *,
        details: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.details = details or []
        self.headers = headers or {}

    def to_response(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


class UserNotFoundError(AppError):
    code = CODE_USER_NOT_FOUND
    status_code = 404

    def __init__(self, user_id: str):
        super().__init__(f"No user found with id '{user_id}'", details=[{"field": "user_id", "issue": "not found"}])


class InvalidUUIDError(AppError):
    code = CODE_INVALID_UUID
    status_code = 400

    def __init__(self, value: str):
        super().__init__(f"'{value}' is not a valid UUID", details=[{"field": "user_id", "issue": "invalid uuid"}])


class InvalidCategoryError(AppError):
    code = CODE_INVALID_CATEGORY
    status_code = 422

    def __init__(self, category: str, allowed: list[str]):
        super().__init__(
            f"Category '{category}' is not allowed",
            details=[{"field": "category", "issue": f"must be one of: {', '.join(allowed)}"}],
        )


class RateLimitedError(AppError):
    code = CODE_RATE_LIMITED
    status_code = 429

    def __init__(self, retry_after: int):
        super().__init__(
            f"Rate limit exceeded; retry after {retry_after}s",
            headers={"Retry-After": str(retry_after)},
        )


class InsufficientFundsError(AppError):
    code = CODE_INSUFFICIENT_FUNDS
    status_code = 402

    def __init__(self, attempted_balance: float, floor: float):
        super().__init__(
            f"Debit would push balance to {attempted_balance:.2f}, below the {floor:.2f} floor",
            details=[{"field": "amount", "issue": "balance floor breach"}],
        )


class ServiceUnavailableError(AppError):
    code = CODE_SERVICE_UNAVAILABLE
    status_code = 503

    def __init__(self, message: str = "Service temporarily unavailable", retry_after: int = 5):
        super().__init__(message, headers={"Retry-After": str(retry_after)})


def _validation_response(detail: Any) -> tuple[dict[str, Any], int]:
    """Translate FastAPI/Pydantic validation errors into the envelope."""
    details: list[dict[str, Any]] = []
    if isinstance(detail, list):
        for err in detail:
            loc = err.get("loc", [])
            # Prefer the last field name in the location tuple.
            field = loc[-1] if loc else "?"
            details.append({"field": str(field), "issue": " ".join(str(m) for m in err.get("msg", "").split())})
    body = {"error": {"code": CODE_VALIDATION_ERROR, "message": "Request validation failed", "details": details}}
    return body, 400


def register_exception_handlers(app: FastAPI) -> None:
    """Wire all error paths to the shared envelope."""

    @app.exception_handler(AppError)
    async def _app_error_handler(_: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content=exc.to_response(), headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(_: Request, exc: RequestValidationError):
        body, status = _validation_response(exc.errors())
        return JSONResponse(status_code=status, content=body)

    @app.exception_handler(Exception)
    async def _global_handler(request: Request, exc: Exception):
        # Never leak stack traces — log full traceback server-side, generic
        # message to the client (REQUIREMENTS §10.3).
        logger.exception("Unhandled error on %s %s", request.method, request.url)
        return JSONResponse(
            status_code=500,
            content={"error": {"code": CODE_INTERNAL_ERROR, "message": "An unexpected error occurred", "details": []}},
        )
