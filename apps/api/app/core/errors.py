"""Centralised error types and handlers.

Every error response has the same shape:
    {"error": {"code": "...", "message": "...", "request_id": "..."}}
"""

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base class for expected, domain-level failures."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "bad_request"

    def __init__(
        self, message: str, *, details: Any = None, headers: dict[str, str] | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details
        self.headers = headers


class UnauthorizedError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthorized"

    def __init__(self, message: str = "Authentication required") -> None:
        super().__init__(message, headers={"WWW-Authenticate": "Bearer"})


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class UnprocessableError(AppError):
    """The request is well-formed but violates a domain rule."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "unprocessable"


class AssistantDisabledError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "assistant_disabled"


class AssistantQuotaError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "assistant_quota_exceeded"

    def __init__(self, message: str, *, retry_after: int) -> None:
        super().__init__(message, headers={"Retry-After": str(retry_after)})


class AssistantUnavailableError(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "assistant_unavailable"


class TooManyRequestsError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"

    def __init__(self, message: str, *, retry_after: int) -> None:
        super().__init__(message, headers={"Retry-After": str(retry_after)})


def error_body(
    code: str, message: str, request: Request | None, details: Any = None
) -> dict[str, Any]:
    """The single error envelope used by every handler and middleware."""
    body: dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
            "request_id": getattr(request.state, "request_id", None) if request else None,
        }
    }
    if details is not None:
        body["error"]["details"] = details
    return body


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.code, exc.message, request, exc.details),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=error_body(
                "validation_error",
                "Request validation failed",
                request,
                # jsonable_encoder keeps this serialisable (ctx may hold exceptions).
                details=[
                    {"loc": err.get("loc"), "msg": err.get("msg"), "type": err.get("type")}
                    for err in exc.errors()
                ],
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body("http_error", str(exc.detail), request),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception", extra={"path": request.url.path})
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_body("internal_error", "Internal server error", request),
        )
