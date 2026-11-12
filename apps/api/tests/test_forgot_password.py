"""Self-service password reset by email (forgot password)."""

import hashlib
import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth import password_reset
from app.modules.auth.models import PasswordResetToken
from app.modules.backup.mailer import mailer_dependency
from tests.backup_fakes import RecordingMailer
from tests.support import DEFAULT_PASSWORD, login, make_user

REQUEST = "/api/v1/auth/password-reset/request"
CONFIRM = "/api/v1/auth/password-reset/confirm"
NEW_PASSWORD = "Fresh-Harvest-2026"
INVALID_LINK_AR = "رابط تغيير كلمة المرور غير صالح أو انتهت صلاحيته. اطلب رابطًا جديدًا."


@pytest.fixture(autouse=True)
def no_padding(monkeypatch: pytest.MonkeyPatch) -> None:
    """The constant response time would slow every test down."""
    monkeypatch.setattr(password_reset, "MIN_REQUEST_SECONDS", 0.0)


@pytest.fixture
def mailer(test_app: FastAPI) -> Iterator[RecordingMailer]:
    recorder = RecordingMailer()
    test_app.dependency_overrides[mailer_dependency] = lambda: recorder
    yield recorder
    test_app.dependency_overrides.pop(mailer_dependency, None)


async def _user(owner_session: AsyncSession) -> str:
    user = await make_user(owner_session)
    await owner_session.commit()
    return user.email


async def test_known_email_gets_a_link(
    client: AsyncClient, owner_session: AsyncSession, mailer: RecordingMailer
) -> None:
    email = await _user(owner_session)

    response = await client.post(REQUEST, json={"email": email.upper()})

    assert response.status_code == 202
    [message] = mailer.sent
    assert message.to == email
    assert "http://localhost:3000/reset-password?token=" in message.body
    assert "30" in message.body


async def test_unknown_email_gets_the_same_answer(
    client: AsyncClient, owner_session: AsyncSession, mailer: RecordingMailer
) -> None:
    email = await _user(owner_session)
    known = await client.post(REQUEST, json={"email": email})
    unknown = await client.post(REQUEST, json={"email": "nobody-here@example.com"})

    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert len(mailer.sent) == 1


async def test_reset_changes_password_and_ends_sessions(
    client: AsyncClient, owner_session: AsyncSession, mailer: RecordingMailer
) -> None:
    email = await _user(owner_session)
    await login(client, email)  # sets the refresh cookie
    assert (await client.post("/api/v1/auth/refresh", json={})).status_code == 200
    await client.post(REQUEST, json={"email": email})

    response = await client.post(
        CONFIRM, json={"token": mailer.last_token(), "new_password": NEW_PASSWORD}
    )

    assert response.status_code == 204, response.text
    assert (await client.post("/api/v1/auth/refresh", json={})).status_code == 401
    old = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": DEFAULT_PASSWORD}
    )
    assert old.status_code == 401
    await login(client, email, NEW_PASSWORD)


async def test_link_works_once(
    client: AsyncClient, owner_session: AsyncSession, mailer: RecordingMailer
) -> None:
    email = await _user(owner_session)
    await client.post(REQUEST, json={"email": email})
    token = mailer.last_token()
    await client.post(CONFIRM, json={"token": token, "new_password": NEW_PASSWORD})

    again = await client.post(CONFIRM, json={"token": token, "new_password": "Another-One-2026"})

    assert again.status_code == 400
    assert again.json()["error"]["message"] == INVALID_LINK_AR


async def test_expired_link_refused(
    client: AsyncClient, owner_session: AsyncSession, mailer: RecordingMailer
) -> None:
    email = await _user(owner_session)
    await client.post(REQUEST, json={"email": email})
    token = mailer.last_token()
    await owner_session.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.token_hash == hashlib.sha256(token.encode()).hexdigest())
        .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    await owner_session.commit()

    response = await client.post(CONFIRM, json={"token": token, "new_password": NEW_PASSWORD})

    assert response.status_code == 400
    await login(client, email)  # old password still works


async def test_older_links_die_after_a_reset(
    client: AsyncClient, owner_session: AsyncSession, mailer: RecordingMailer
) -> None:
    email = await _user(owner_session)
    await client.post(REQUEST, json={"email": email})
    first = mailer.last_token()
    await client.post(REQUEST, json={"email": email})
    second = mailer.last_token()
    await client.post(CONFIRM, json={"token": second, "new_password": NEW_PASSWORD})

    response = await client.post(CONFIRM, json={"token": first, "new_password": "Another-One-2026"})

    assert response.status_code == 400


async def test_weak_password_refused_in_arabic(
    client: AsyncClient, owner_session: AsyncSession, mailer: RecordingMailer
) -> None:
    email = await _user(owner_session)
    await client.post(REQUEST, json={"email": email})
    token = mailer.last_token()

    digits = await client.post(CONFIRM, json={"token": token, "new_password": "1234509876"})

    assert digits.status_code == 422
    assert digits.json()["error"]["message"] == "كلمة المرور لا يجب أن تكون أرقامًا فقط."
    # The link was not spent by the refused attempt.
    ok = await client.post(CONFIRM, json={"token": token, "new_password": NEW_PASSWORD})
    assert ok.status_code == 204


async def test_three_emails_per_address_per_hour(
    client: AsyncClient, owner_session: AsyncSession, mailer: RecordingMailer
) -> None:
    email = await _user(owner_session)

    responses = [await client.post(REQUEST, json={"email": email}) for _ in range(4)]

    assert [r.status_code for r in responses] == [202, 202, 202, 202]
    assert len(mailer.sent) == 3


async def test_token_stored_hashed(
    client: AsyncClient, owner_session: AsyncSession, mailer: RecordingMailer
) -> None:
    email = await _user(owner_session)
    await client.post(REQUEST, json={"email": email})
    token = mailer.last_token()

    hashes = (await owner_session.execute(select(PasswordResetToken.token_hash))).scalars().all()

    assert hashlib.sha256(token.encode()).hexdigest() in hashes
    assert token not in hashes


async def test_without_mail_config_still_answers_the_same(
    client: AsyncClient, owner_session: AsyncSession, test_app: FastAPI
) -> None:
    test_app.dependency_overrides[mailer_dependency] = lambda: None
    email = await _user(owner_session)

    response = await client.post(REQUEST, json={"email": email})

    assert response.status_code == 202
    test_app.dependency_overrides.pop(mailer_dependency, None)


async def test_logs_never_hold_the_address(
    client: AsyncClient,
    owner_session: AsyncSession,
    mailer: RecordingMailer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    email = await _user(owner_session)
    caplog.set_level(logging.INFO)

    await client.post(REQUEST, json={"email": email})
    await client.post(CONFIRM, json={"token": mailer.last_token(), "new_password": NEW_PASSWORD})

    assert all(email not in record.getMessage() for record in caplog.records)
    assert all(email not in str(vars(record)) for record in caplog.records)


async def test_unknown_email_waits_as_long_as_a_real_send(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, mailer: RecordingMailer
) -> None:
    import time

    monkeypatch.setattr(password_reset, "MIN_REQUEST_SECONDS", 0.3)
    started = time.monotonic()

    await client.post(REQUEST, json={"email": "nobody-at-all@example.com"})

    assert time.monotonic() - started >= 0.3
