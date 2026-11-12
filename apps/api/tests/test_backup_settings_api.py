"""Owner settings for the daily backup email, and the confirmation link."""

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog
from app.modules.backup.mailer import mailer_dependency
from app.modules.backup.models import BackupSettings
from app.modules.identity.models import MembershipRole
from tests.backup_fakes import RecordingMailer
from tests.support import seeded_login

BACKUP = "/api/v1/tenants/current/backup"
CONFIRM = "/api/v1/backup/confirm"
INVALID_LINK_AR = "رابط التأكيد غير صالح أو انتهت صلاحيته. احفظ العنوان مرة أخرى لإرسال رابط جديد."


@pytest.fixture
def mailer(test_app: FastAPI) -> Iterator[RecordingMailer]:
    recorder = RecordingMailer()
    test_app.dependency_overrides[mailer_dependency] = lambda: recorder
    yield recorder
    test_app.dependency_overrides.pop(mailer_dependency, None)


async def _settings_row(owner_session: AsyncSession, tenant_id: object) -> BackupSettings:
    owner_session.expire_all()
    row = await owner_session.get(BackupSettings, tenant_id)
    assert row is not None
    return row


async def test_owner_saves_address_and_gets_link(
    client: AsyncClient, owner_session: AsyncSession, mailer: RecordingMailer
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)

    response = await client.put(BACKUP, json={"email": "Owner@Example.com"}, headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "pending"
    assert body["email"] == "owner@example.com"
    assert body["mail_configured"] is True
    [email] = mailer.sent
    assert email.to == "owner@example.com"
    assert email.attachment is None
    assert "http://localhost:3000/backup/confirm?token=" in email.body


@pytest.mark.parametrize(
    "role", [MembershipRole.MANAGER, MembershipRole.INVENTORY_MANAGER, MembershipRole.CASHIER]
)
async def test_non_owner_roles_forbidden(
    client: AsyncClient, owner_session: AsyncSession, mailer: RecordingMailer, role: MembershipRole
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session, role=role)

    assert (await client.get(BACKUP, headers=headers)).status_code == 403
    put = await client.put(BACKUP, json={"email": "x@example.com"}, headers=headers)
    assert put.status_code == 403
    assert (await client.delete(BACKUP, headers=headers)).status_code == 403
    assert mailer.sent == []


async def test_confirm_activates(
    client: AsyncClient, owner_session: AsyncSession, mailer: RecordingMailer
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    await client.put(BACKUP, json={"email": "owner@example.com"}, headers=headers)

    response = await client.post(CONFIRM, json={"token": mailer.last_token()})

    assert response.status_code == 204, response.text
    status = (await client.get(BACKUP, headers=headers)).json()
    assert status["status"] == "active"


async def test_confirm_twice_refused(
    client: AsyncClient, owner_session: AsyncSession, mailer: RecordingMailer
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    await client.put(BACKUP, json={"email": "owner@example.com"}, headers=headers)
    token = mailer.last_token()
    await client.post(CONFIRM, json={"token": token})

    again = await client.post(CONFIRM, json={"token": token})

    assert again.status_code == 400
    assert again.json()["error"]["message"] == INVALID_LINK_AR


async def test_expired_token_refused(
    client: AsyncClient, owner_session: AsyncSession, mailer: RecordingMailer
) -> None:
    _, headers, tenant, _ = await seeded_login(client, owner_session)
    await client.put(BACKUP, json={"email": "owner@example.com"}, headers=headers)
    await owner_session.execute(
        update(BackupSettings)
        .where(BackupSettings.tenant_id == tenant.id)
        .values(confirm_expires_at=datetime.now(UTC) - timedelta(minutes=1))
    )
    await owner_session.commit()

    response = await client.post(CONFIRM, json={"token": mailer.last_token()})

    assert response.status_code == 400
    assert (await client.get(BACKUP, headers=headers)).json()["status"] == "pending"


async def test_old_token_dies_when_address_changes(
    client: AsyncClient, owner_session: AsyncSession, mailer: RecordingMailer
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    await client.put(BACKUP, json={"email": "first@example.com"}, headers=headers)
    old_token = mailer.last_token()
    await client.put(BACKUP, json={"email": "second@example.com"}, headers=headers)

    old = await client.post(CONFIRM, json={"token": old_token})
    new = await client.post(CONFIRM, json={"token": mailer.last_token()})

    assert old.status_code == 400
    assert old.json()["error"]["message"] == INVALID_LINK_AR
    assert new.status_code == 204
    assert (await client.get(BACKUP, headers=headers)).json()["email"] == "second@example.com"


async def test_saving_same_active_address_sends_nothing(
    client: AsyncClient, owner_session: AsyncSession, mailer: RecordingMailer
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    await client.put(BACKUP, json={"email": "owner@example.com"}, headers=headers)
    await client.post(CONFIRM, json={"token": mailer.last_token()})

    again = await client.put(BACKUP, json={"email": "owner@example.com"}, headers=headers)

    assert again.json()["status"] == "active"
    assert len(mailer.sent) == 1


async def test_stop_sets_stopped_and_audits(
    client: AsyncClient, owner_session: AsyncSession, mailer: RecordingMailer
) -> None:
    _, headers, tenant, user = await seeded_login(client, owner_session)
    await client.put(BACKUP, json={"email": "owner@example.com"}, headers=headers)
    await client.post(CONFIRM, json={"token": mailer.last_token()})

    response = await client.delete(BACKUP, headers=headers)

    assert response.status_code == 204
    assert (await client.get(BACKUP, headers=headers)).json()["status"] == "stopped"
    actions = (
        await owner_session.execute(
            select(AuditLog.action, AuditLog.actor_id).where(AuditLog.tenant_id == tenant.id)
        )
    ).all()
    assert ("backup.address_set", user.id) in actions
    assert ("backup.confirmed", None) in actions
    assert ("backup.stopped", user.id) in actions


async def test_save_without_mailer_config_reports_not_configured(
    client: AsyncClient, owner_session: AsyncSession, test_app: FastAPI
) -> None:
    test_app.dependency_overrides[mailer_dependency] = lambda: None
    _, headers, tenant, _ = await seeded_login(client, owner_session)

    status = (await client.get(BACKUP, headers=headers)).json()
    response = await client.put(BACKUP, json={"email": "owner@example.com"}, headers=headers)

    assert status == {
        "email": None,
        "status": None,
        "last_sent_at": None,
        "last_error_ar": None,
        "consecutive_failures": 0,
        "manual_sends_left": 3,
        "mail_configured": False,
    }
    assert response.status_code == 503
    assert response.json()["error"]["message"] == "الإرسال غير مُعدّ."
    assert await owner_session.get(BackupSettings, tenant.id) is None


async def test_failed_link_email_stores_nothing(
    client: AsyncClient, owner_session: AsyncSession, mailer: RecordingMailer
) -> None:
    _, headers, tenant, _ = await seeded_login(client, owner_session)
    mailer.failures = ["عنوان البريد مرفوض."]

    response = await client.put(BACKUP, json={"email": "nobody@example.com"}, headers=headers)

    assert response.status_code == 422
    assert response.json()["error"]["message"] == "عنوان البريد مرفوض."
    assert await owner_session.get(BackupSettings, tenant.id) is None


async def test_token_never_stored_in_clear(
    client: AsyncClient, owner_session: AsyncSession, mailer: RecordingMailer
) -> None:
    _, headers, tenant, _ = await seeded_login(client, owner_session)
    await client.put(BACKUP, json={"email": "owner@example.com"}, headers=headers)
    token = mailer.last_token()

    row = await _settings_row(owner_session, tenant.id)

    assert row.confirm_token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert row.confirm_token_hash != token


async def test_confirmation_emails_capped_per_day(
    client: AsyncClient, owner_session: AsyncSession, mailer: RecordingMailer
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    for n in range(5):
        ok = await client.put(BACKUP, json={"email": f"o{n}@example.com"}, headers=headers)
        assert ok.status_code == 200, ok.text

    sixth = await client.put(BACKUP, json={"email": "o6@example.com"}, headers=headers)

    assert sixth.status_code == 429
    assert sixth.json()["error"]["message"] == "أرسلنا روابط تأكيد كثيرة اليوم. حاول غدًا."
    assert len(mailer.sent) == 5


def test_app_password_whitespace_is_ignored() -> None:
    from pydantic import SecretStr

    from app.core.config import get_settings
    from app.modules.backup.mailer import GmailMailer, get_mailer

    settings = get_settings().model_copy(
        update={
            "gmail_user": " shop@gmail.com ",
            "gmail_app_password": SecretStr("abcd efgh ijkl mnop\r\n"),
        }
    )

    mailer = get_mailer(settings)

    assert isinstance(mailer, GmailMailer)
    assert mailer._password == "abcdefghijklmnop"
    assert mailer._user == "shop@gmail.com"
