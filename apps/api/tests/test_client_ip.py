"""Client IP resolution behind a trusted proxy (Vercel) and without one."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.core.client_ip import client_ip
from app.core.config import get_settings
from tests.support import seed_member


def _request(headers: dict[str, str], peer: str = "10.0.0.9") -> Request:
    scope = {
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": (peer, 1234),
    }
    return Request(scope)


def test_headers_ignored_unless_proxy_is_trusted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "trust_proxy_headers", False)

    assert client_ip(_request({"x-forwarded-for": "1.2.3.4"})) == "10.0.0.9"


def test_trusted_proxy_headers_in_priority_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "trust_proxy_headers", True)

    assert client_ip(_request({"x-vercel-forwarded-for": "5.5.5.5", "x-real-ip": "6.6.6.6"})) == (
        "5.5.5.5"
    )
    assert client_ip(_request({"x-real-ip": "6.6.6.6", "x-forwarded-for": "7.7.7.7"})) == "6.6.6.6"
    # The first entry of X-Forwarded-For is the original client.
    assert client_ip(_request({"x-forwarded-for": " 8.8.8.8 , 10.1.1.1"})) == "8.8.8.8"
    # No proxy headers at all: fall back to the socket peer.
    assert client_ip(_request({})) == "10.0.0.9"


async def test_shops_behind_one_proxy_get_separate_login_limits(
    client: AsyncClient, owner_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On Vercel every request arrives from the platform; the real IP is in a header."""
    settings = get_settings()
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    user, _, _ = await seed_member(owner_session)
    wrong = {"email": user.email, "password": "WrongOne!234"}

    shop_a = {"x-real-ip": "41.0.0.1"}
    for _ in range(settings.auth_rate_limit_attempts):
        await client.post("/api/v1/auth/login", json=wrong, headers=shop_a)
    blocked = await client.post("/api/v1/auth/login", json=wrong, headers=shop_a)

    # A different shop behind the same proxy is not affected by shop A's limit.
    other_shop = await client.post(
        "/api/v1/auth/login", json=wrong, headers={"x-real-ip": "41.0.0.2"}
    )

    assert blocked.status_code == 429
    assert other_shop.status_code == 401
