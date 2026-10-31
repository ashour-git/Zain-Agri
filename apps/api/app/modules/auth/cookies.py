"""Refresh-token cookie handling.

The token is only ever *set* here and only ever *read* by the auth router from
``request.cookies``; it is never returned in a JSON body, so JavaScript cannot
read it (HttpOnly) and it never reaches localStorage.
"""

from fastapi import Response

from app.core.config import Settings


def set_refresh_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=token,
        max_age=settings.refresh_token_ttl_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        # Lax still blocks cross-site POSTs. If the web app is ever served from
        # a different site than the API, set REFRESH_COOKIE_SAMESITE=none and
        # keep Secure on — see docs/security/AUTHENTICATION.md.
        samesite="lax",
        path=settings.refresh_cookie_path,
    )


def clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        path=settings.refresh_cookie_path,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="lax",
    )
