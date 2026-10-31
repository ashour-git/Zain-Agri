"""Cross-site request forgery protection for cookie-authenticated requests.

The refresh token lives in an HttpOnly cookie, so a browser attaches it to any
request that reaches the API. Two independent controls stop a foreign origin
from using it:

1. ``SameSite=Lax`` on the cookie, which browsers honour for cross-site POSTs.
2. This middleware: any unsafe request that carries the cookie must also prove
   its origin with an ``Origin`` (or ``Referer``) header naming an allowed
   origin. A request without one is rejected.

Requests that carry no refresh cookie are unaffected — bearer-token calls
cannot be forged by a third-party page because the token is never in a cookie.
"""

import logging
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from app.core.errors import error_body

logger = logging.getLogger("zain.security")

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


def _origin_of(value: str) -> str | None:
    parts = urlsplit(value)
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}"


class OriginGuardMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, allowed_origins: list[str], cookie_name: str) -> None:
        super().__init__(app)
        self.allowed_origins = {origin.rstrip("/") for origin in allowed_origins}
        self.cookie_name = cookie_name

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method in SAFE_METHODS or self.cookie_name not in request.cookies:
            return await call_next(request)

        origin = request.headers.get("origin")
        if origin is None:
            referer = request.headers.get("referer")
            origin = _origin_of(referer) if referer else None

        if origin is None or origin.rstrip("/") not in self.allowed_origins:
            logger.warning(
                "csrf_origin_rejected",
                extra={
                    "event": "auth.csrf_rejected",
                    "path": request.url.path,
                    "ip": request.client.host if request.client else None,
                },
            )
            return JSONResponse(
                status_code=403,
                content=error_body(
                    "csrf_rejected",
                    "Request origin is not allowed to change authentication state",
                    request,
                ),
            )

        return await call_next(request)


def install_origin_guard(app: FastAPI, *, allowed_origins: list[str], cookie_name: str) -> None:
    if not allowed_origins:
        logger.warning("csrf_guard_disabled", extra={"event": "auth.csrf_disabled"})
        return
    app.add_middleware(
        OriginGuardMiddleware, allowed_origins=allowed_origins, cookie_name=cookie_name
    )
