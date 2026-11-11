"""Admin password reset (reset_password.py), for owners locked out of their account.

There is no email delivery yet, so a self-service "forgot password" is not
possible. An administrator runs the script; it sets a new password and ends
every open session of that user.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.service import reset_password
from tests.support import DEFAULT_PASSWORD

NEW_PASSWORD = "Fresh-Reset-Pass-2026"


async def _register(client: AsyncClient) -> str:
    email = f"reset-{uuid.uuid4().hex[:10]}@example.com"
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": DEFAULT_PASSWORD, "full_name": "مالك"},
    )
    assert response.status_code == 201, response.text
    return email


async def test_reset_sets_new_password_and_old_one_stops_working(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = await _register(client)

    assert await reset_password(db_session, email=email, new_password=NEW_PASSWORD) is True

    old = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": DEFAULT_PASSWORD}
    )
    new = await client.post("/api/v1/auth/login", json={"email": email, "password": NEW_PASSWORD})
    assert old.status_code == 401
    assert new.status_code == 200


async def test_reset_ends_existing_sessions(client: AsyncClient, db_session: AsyncSession) -> None:
    email = await _register(client)  # registration leaves a refresh cookie on the client
    before = await client.post("/api/v1/auth/refresh", json={})
    assert before.status_code == 200, before.text

    await reset_password(db_session, email=email, new_password=NEW_PASSWORD)

    after = await client.post("/api/v1/auth/refresh", json={})
    assert after.status_code == 401


async def test_reset_matches_email_case_insensitively(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = await _register(client)

    assert await reset_password(db_session, email=email.upper(), new_password=NEW_PASSWORD)


async def test_reset_unknown_email_returns_false(db_session: AsyncSession) -> None:
    assert (
        await reset_password(db_session, email="nobody-here@example.com", new_password=NEW_PASSWORD)
        is False
    )


@pytest.mark.parametrize("weak", ["short", "1234567890", "password123"])
async def test_reset_refuses_weak_passwords(db_session: AsyncSession, weak: str) -> None:
    with pytest.raises(ValueError):
        await reset_password(db_session, email="any@example.com", new_password=weak)
