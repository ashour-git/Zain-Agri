"""Request correlation and access logging."""

import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.infrastructure.db import timing as db_timing

logger = logging.getLogger("zain.access")

REQUEST_ID_HEADER = "X-Request-ID"


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        request.state.request_id = request_id
        started = time.perf_counter()
        db = db_timing.start()

        response = await call_next(request)

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers["Server-Timing"] = (
            f'db;dur={db.query_ms:.1f};desc="{db.queries} queries", '
            f'db-connect;dur={db.connect_ms:.1f};desc="{db.connects} new", '
            f"total;dur={duration_ms:.1f}"
        )
        logger.info(
            "%s %s -> %s",
            request.method,
            request.url.path,
            response.status_code,
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "db_ms": round(db.query_ms, 1),
                "db_queries": db.queries,
                "db_connect_ms": round(db.connect_ms, 1),
                "db_connects": db.connects,
            },
        )
        return response
