"""Authentication flows: registration, login, tokens, rotation and sessions."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.auth.models import RefreshSession
from app.modules.identity.models import (
    Membership,
    MembershipRole,
    MembershipStatus,
    Tenant,
    User,
)
from tests.support import (
    DEFAULT_PASSWORD,
    auth_header,
    login,
    make_membership,
    make_tenant,
    make_user,
    seed_member,
)

COOKIE = "zain_refresh"


# --- registration -----------------------------------------------------------


async def test_register_returns_tokens_and_sets_httponly_cookie(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    email = f"new-{uuid.uuid4().hex[:10]}@example.com"
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": DEFAULT_PASSWORD, "full_name": "صاحب المتجر"},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user"]["email"] == email
    assert body["tenant"] is None
    assert body["requires_tenant_selection"] is True

    # The refresh token must exist only as a cookie, never in the payload.
    assert body["access_token"]
    assert "refresh_token" not in body
    raw_refresh = response.cookies.get(COOKIE)
    assert raw_refresh
    assert raw_refresh not in response.text

    set_cookie = response.headers["set-cookie"]
    assert "HttpOnly" in set_cookie
    assert "Path=/api/v1/auth" in set_cookie
    assert "SameSite=lax" in set_cookie.lower() or "samesite=lax" in set_cookie.lower()

    # Only the digest is persisted.
    stored = (await owner_session.execute(select(RefreshSession.token_hash))).scalars().all()
    assert all(len(digest) == 64 for digest in stored)
    assert raw_refresh not in stored


async def test_register_stores_argon2id_hash_never_the_password(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    email = f"hash-{uuid.uuid4().hex[:10]}@example.com"
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": DEFAULT_PASSWORD, "full_name": "مستخدم"},
    )

    user = (await owner_session.execute(select(User).where(User.email == email))).scalar_one()
    assert user.password_hash.startswith("$argon2id$")
    assert DEFAULT_PASSWORD not in user.password_hash
    assert "argon2id" in user.password_hash


async def test_register_rejects_duplicate_email(client: AsyncClient) -> None:
    email = f"dupe-{uuid.uuid4().hex[:10]}@example.com"
    payload = {"email": email, "password": DEFAULT_PASSWORD, "full_name": "مستخدم"}

    first = await client.post("/api/v1/auth/register", json=payload)
    second = await client.post("/api/v1/auth/register", json=payload)

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "conflict"


@pytest.mark.parametrize("password", ["short", "1234567890", "password123"])
async def test_register_rejects_weak_passwords(client: AsyncClient, password: str) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"weak-{uuid.uuid4().hex[:10]}@example.com",
            "password": password,
            "full_name": "مستخدم",
        },
    )
    assert response.status_code == 422


# --- login ------------------------------------------------------------------


async def test_unknown_email_and_wrong_password_are_indistinguishable(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    user, _, _ = await seed_member(owner_session)

    unknown = await client.post(
        "/api/v1/auth/login",
        json={"email": f"ghost-{uuid.uuid4().hex[:8]}@example.com", "password": DEFAULT_PASSWORD},
    )
    wrong = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "NotTheRightOne!23"},
    )

    assert unknown.status_code == 401
    assert wrong.status_code == 401
    assert unknown.json()["error"]["message"] == wrong.json()["error"]["message"]
    assert unknown.json()["error"]["code"] == wrong.json()["error"]["code"]


async def test_inactive_account_cannot_log_in(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    user = await make_user(owner_session, is_active=False)
    tenant = await make_tenant(owner_session)
    await make_membership(owner_session, tenant=tenant, user=user)
    await owner_session.commit()

    response = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": DEFAULT_PASSWORD}
    )

    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Invalid email or password"


async def test_login_with_single_membership_binds_the_workspace(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    user, tenant, _ = await seed_member(owner_session)

    body = await login(client, user.email)

    assert body["tenant"]["id"] == str(tenant.id)
    assert body["role"] == "owner"
    assert body["requires_tenant_selection"] is False
    assert "tenant.settings.manage" in body["permissions"]
    assert "finance.view" in body["permissions"]


async def test_login_with_multiple_memberships_requires_selection(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    user = await make_user(owner_session)
    first = await make_tenant(owner_session, name="الفرع الأول")
    second = await make_tenant(owner_session, name="الفرع الثاني")
    await make_membership(owner_session, tenant=first, user=user, role=MembershipRole.OWNER)
    await make_membership(owner_session, tenant=second, user=user, role=MembershipRole.MANAGER)
    await owner_session.commit()

    body = await login(client, user.email)

    assert body["tenant"] is None
    assert body["requires_tenant_selection"] is True
    assert {t["id"] for t in body["tenants"]} == {str(first.id), str(second.id)}


async def test_login_can_select_a_workspace_explicitly(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    user = await make_user(owner_session)
    first = await make_tenant(owner_session, name="الفرع الأول")
    second = await make_tenant(owner_session, name="الفرع الثاني")
    await make_membership(owner_session, tenant=first, user=user, role=MembershipRole.OWNER)
    await make_membership(owner_session, tenant=second, user=user, role=MembershipRole.CASHIER)
    await owner_session.commit()

    body = await login(client, user.email, tenant_id=second.id)

    assert body["tenant"]["id"] == str(second.id)
    assert body["role"] == "cashier"


async def test_login_cannot_select_a_foreign_workspace(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    user, _, _ = await seed_member(owner_session)
    other_tenant = await make_tenant(owner_session, name="متجر آخر")
    await owner_session.commit()

    response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": user.email,
            "password": DEFAULT_PASSWORD,
            "tenant_id": str(other_tenant.id),
        },
    )

    assert response.status_code == 403


async def test_login_is_rate_limited(client: AsyncClient, owner_session: AsyncSession) -> None:
    user, _, _ = await seed_member(owner_session)
    settings = get_settings()

    statuses = []
    for _ in range(settings.auth_rate_limit_attempts + 2):
        response = await client.post(
            "/api/v1/auth/login", json={"email": user.email, "password": "WrongOne!234"}
        )
        statuses.append(response.status_code)

    # The first `attempts` calls are evaluated normally, the rest are refused
    # before any password work happens.
    assert (
        statuses[: settings.auth_rate_limit_attempts] == [401] * settings.auth_rate_limit_attempts
    )
    assert statuses[settings.auth_rate_limit_attempts :] == [429, 429]


# --- access tokens ----------------------------------------------------------


def _forge(
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    lifetime: timedelta,
    secret: str | None = None,
    typ: str = "access",
) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(user_id),
            "sid": str(session_id),
            "tid": None,
            "rol": None,
            "jti": uuid.uuid4().hex,
            "typ": typ,
            "iat": int(now.timestamp()),
            "exp": int((now + lifetime).timestamp()),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
        },
        secret or settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


async def test_me_requires_a_token(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_garbage_token_is_rejected(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401


async def test_token_signed_with_another_secret_is_rejected(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    user, _, _ = await seed_member(owner_session)
    forged = _forge(
        user_id=user.id,
        session_id=uuid.uuid4(),
        lifetime=timedelta(minutes=5),
        secret="attacker-controlled-secret-value-000000",
    )

    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401


async def test_expired_access_token_is_rejected(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    body = await login(client, (await seed_member(owner_session))[0].email)
    claims = jwt.decode(
        body["access_token"],
        get_settings().jwt_secret_key.get_secret_value(),
        algorithms=["HS256"],
        audience=get_settings().jwt_audience,
        issuer=get_settings().jwt_issuer,
    )
    expired = _forge(
        user_id=uuid.UUID(claims["sub"]),
        session_id=uuid.UUID(claims["sid"]),
        lifetime=timedelta(seconds=-30),
    )

    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401


async def test_refresh_token_type_cannot_be_used_as_access_token(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    user, _, _ = await seed_member(owner_session)
    body = await login(client, user.email)
    claims = jwt.decode(
        body["access_token"],
        get_settings().jwt_secret_key.get_secret_value(),
        algorithms=["HS256"],
        audience=get_settings().jwt_audience,
        issuer=get_settings().jwt_issuer,
    )
    wrong_type = _forge(
        user_id=uuid.UUID(claims["sub"]),
        session_id=uuid.UUID(claims["sid"]),
        lifetime=timedelta(minutes=5),
        typ="refresh",
    )

    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {wrong_type}"}
    )
    assert response.status_code == 401


async def test_me_reports_identity_and_workspace(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    user, tenant, _ = await seed_member(owner_session)
    body = await login(client, user.email)

    response = await client.get("/api/v1/auth/me", headers=auth_header(body))

    assert response.status_code == 200
    payload = response.json()
    assert payload["user"]["email"] == user.email
    assert payload["tenant"]["id"] == str(tenant.id)
    assert payload["role"] == "owner"
    assert payload["requires_tenant_selection"] is False
    assert "password_hash" not in response.text


# --- refresh rotation -------------------------------------------------------


async def test_refresh_rotates_the_token(client: AsyncClient, owner_session: AsyncSession) -> None:
    user, tenant, _ = await seed_member(owner_session)
    body = await login(client, user.email)
    original = client.cookies.get(COOKIE)

    response = await client.post("/api/v1/auth/refresh", json={})

    assert response.status_code == 200, response.text
    rotated = response.cookies.get(COOKIE)
    assert rotated and rotated != original
    assert response.json()["tenant"]["id"] == str(tenant.id)
    assert response.json()["access_token"] != body["access_token"]


async def test_replayed_refresh_token_revokes_the_whole_family(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    user, _, _ = await seed_member(owner_session)
    await login(client, user.email)
    stolen = client.cookies.get(COOKIE)

    first_rotation = await client.post("/api/v1/auth/refresh", json={})
    assert first_rotation.status_code == 200
    legitimate = first_rotation.cookies.get(COOKIE)

    # The attacker replays the token that was already rotated away.
    client.cookies.clear()
    replay = await client.post(
        "/api/v1/auth/refresh", json={}, headers={"Cookie": f"{COOKIE}={stolen}"}
    )
    assert replay.status_code == 401

    # ...and the thief's replay also kills the legitimate branch.
    client.cookies.clear()
    after = await client.post(
        "/api/v1/auth/refresh", json={}, headers={"Cookie": f"{COOKIE}={legitimate}"}
    )
    assert after.status_code == 401

    families = (
        (
            await owner_session.execute(
                select(RefreshSession.revoked_at).where(RefreshSession.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    assert families and all(revoked is not None for revoked in families)


async def test_refresh_without_cookie_is_unauthorized(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/refresh", json={})
    assert response.status_code == 401


async def test_refresh_cannot_switch_to_a_foreign_workspace(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    user, _, _ = await seed_member(owner_session)
    outsider_tenant = await make_tenant(owner_session, name="متجر الغير")
    await owner_session.commit()
    await login(client, user.email)

    response = await client.post(
        "/api/v1/auth/refresh", json={"tenant_id": str(outsider_tenant.id)}
    )

    assert response.status_code == 403


async def test_refresh_switches_between_own_workspaces(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    user = await make_user(owner_session)
    first = await make_tenant(owner_session, name="الفرع الأول")
    second = await make_tenant(owner_session, name="الفرع الثاني")
    await make_membership(owner_session, tenant=first, user=user, role=MembershipRole.OWNER)
    await make_membership(owner_session, tenant=second, user=user, role=MembershipRole.MANAGER)
    await owner_session.commit()

    body = await login(client, user.email, tenant_id=first.id)
    assert body["tenant"]["id"] == str(first.id)

    response = await client.post("/api/v1/auth/refresh", json={"tenant_id": str(second.id)})

    assert response.status_code == 200
    assert response.json()["tenant"]["id"] == str(second.id)
    assert response.json()["role"] == "manager"


async def test_expired_refresh_session_is_rejected(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    user, _, _ = await seed_member(owner_session)
    await login(client, user.email)

    await owner_session.execute(
        text("UPDATE refresh_sessions SET expires_at = now() - interval '1 day'")
    )
    await owner_session.commit()

    response = await client.post("/api/v1/auth/refresh", json={})
    assert response.status_code == 401


# --- logout, sessions -------------------------------------------------------


async def test_logout_revokes_the_session_and_clears_the_cookie(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    user, _, _ = await seed_member(owner_session)
    body = await login(client, user.email)

    response = await client.post("/api/v1/auth/logout")

    assert response.status_code == 204
    assert client.cookies.get(COOKIE) is None
    cleared = response.headers["set-cookie"]
    assert f"{COOKIE}=" in cleared
    assert "Max-Age=0" in cleared or "expires" in cleared.lower()

    # The access token dies with the session it was minted for.
    me = await client.get("/api/v1/auth/me", headers=auth_header(body))
    assert me.status_code == 401

    refresh = await client.post("/api/v1/auth/refresh", json={})
    assert refresh.status_code == 401


async def test_logout_is_idempotent(client: AsyncClient, owner_session: AsyncSession) -> None:
    user, _, _ = await seed_member(owner_session)
    await login(client, user.email)

    assert (await client.post("/api/v1/auth/logout")).status_code == 204
    assert (await client.post("/api/v1/auth/logout")).status_code == 204


async def test_logout_all_revokes_every_session(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    user, _, _ = await seed_member(owner_session)
    await login(client, user.email)
    second_client_body = await login(client, user.email)
    third_body = await login(client, user.email)

    response = await client.post("/api/v1/auth/logout-all", headers=auth_header(third_body))

    assert response.status_code == 204
    assert response.headers["X-Revoked-Sessions"] == "3"
    assert (
        await client.get("/api/v1/auth/me", headers=auth_header(second_client_body))
    ).status_code == 401

    remaining = (
        (
            await owner_session.execute(
                select(RefreshSession).where(
                    RefreshSession.user_id == user.id, RefreshSession.revoked_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    assert remaining == []


async def test_sessions_are_listed_and_the_current_one_is_marked(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    user, _, _ = await seed_member(owner_session)
    body = await login(client, user.email)
    other = await login(client, user.email)
    assert other["access_token"] != body["access_token"]

    response = await client.get("/api/v1/auth/sessions", headers=auth_header(body))

    assert response.status_code == 200
    sessions = response.json()
    assert len(sessions) == 2
    assert sum(1 for session in sessions if session["is_current"]) == 1
    assert "token_hash" not in response.text


async def test_a_session_can_be_revoked_by_id(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    user, _, _ = await seed_member(owner_session)
    body = await login(client, user.email)
    other = await login(client, user.email)

    listed = await client.get("/api/v1/auth/sessions", headers=auth_header(body))
    victim = next(s for s in listed.json() if not s["is_current"])

    response = await client.delete(
        f"/api/v1/auth/sessions/{victim['id']}", headers=auth_header(body)
    )
    assert response.status_code == 204

    assert (await client.get("/api/v1/auth/me", headers=auth_header(other))).status_code == 401
    assert (await client.get("/api/v1/auth/me", headers=auth_header(body))).status_code == 200


async def test_cannot_revoke_someone_elses_session(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    victim_user, _, _ = await seed_member(owner_session)
    attacker_user, _, _ = await seed_member(owner_session)
    await login(client, victim_user.email)
    victim_sessions = await client.get(
        "/api/v1/auth/sessions", headers=auth_header(await login(client, victim_user.email))
    )
    victim_session_id = victim_sessions.json()[0]["id"]

    attacker = await login(client, attacker_user.email)
    response = await client.delete(
        f"/api/v1/auth/sessions/{victim_session_id}", headers=auth_header(attacker)
    )

    assert response.status_code == 404
    still_alive = await owner_session.get(RefreshSession, uuid.UUID(victim_session_id))
    assert still_alive is not None and still_alive.revoked_at is None


# --- CSRF guard -------------------------------------------------------------


async def test_cookie_mutation_without_an_origin_is_rejected(
    plain_client: AsyncClient, owner_session: AsyncSession
) -> None:
    user, _, _ = await seed_member(owner_session)
    await login(plain_client, user.email)
    assert plain_client.cookies.get(COOKIE)

    response = await plain_client.post("/api/v1/auth/refresh", json={})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_rejected"


async def test_cookie_mutation_from_a_foreign_origin_is_rejected(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    user, _, _ = await seed_member(owner_session)
    await login(client, user.email)

    response = await client.post(
        "/api/v1/auth/refresh", json={}, headers={"Origin": "https://evil.example"}
    )

    assert response.status_code == 403


async def test_safe_methods_do_not_need_an_origin(
    plain_client: AsyncClient, owner_session: AsyncSession
) -> None:
    user, _, _ = await seed_member(owner_session)
    body = await login(plain_client, user.email)

    response = await plain_client.get("/api/v1/auth/me", headers=auth_header(body))

    assert response.status_code == 200


# --- onboarding -------------------------------------------------------------


async def test_register_then_create_workspace_makes_the_caller_owner(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    email = f"owner-{uuid.uuid4().hex[:10]}@example.com"
    registered = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": DEFAULT_PASSWORD, "full_name": "صاحب المتجر"},
    )
    token = registered.json()["access_token"]

    created = await client.post(
        "/api/v1/tenants",
        json={"name": "مؤسسة زين الزراعية"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert created.status_code == 201, created.text
    payload = created.json()
    assert payload["role"] == "owner"
    assert payload["tenant"]["slug"]
    assert payload["tenant"]["status"] == "active"
    assert "tenant.settings.manage" in payload["permissions"]

    # The session is re-bound, so the new workspace is immediately usable.
    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {payload['access_token']}"}
    )
    assert me.json()["tenant"]["id"] == payload["tenant"]["id"]
    assert me.json()["role"] == "owner"

    members = await client.get(
        "/api/v1/tenants/current/members",
        headers={"Authorization": f"Bearer {payload['access_token']}"},
    )
    assert members.status_code == 200
    assert [m["email"] for m in members.json()] == [email]
    assert members.json()[0]["role"] == "owner"


async def test_workspace_slugs_stay_unique(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    slugs = []
    for _ in range(2):
        email = f"slug-{uuid.uuid4().hex[:10]}@example.com"
        registered = await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": DEFAULT_PASSWORD, "full_name": "تاجر"},
        )
        created = await client.post(
            "/api/v1/tenants",
            json={"name": "Zain Agri Store"},
            headers={"Authorization": f"Bearer {registered.json()['access_token']}"},
        )
        assert created.status_code == 201, created.text
        slugs.append(created.json()["tenant"]["slug"])

    assert slugs[0] != slugs[1]
    assert slugs[0] == "zain-agri-store"


async def test_workspace_name_is_validated(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    email = f"name-{uuid.uuid4().hex[:10]}@example.com"
    registered = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": DEFAULT_PASSWORD, "full_name": "تاجر"},
    )
    headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}

    blank = await client.post("/api/v1/tenants", json={"name": "   "}, headers=headers)
    too_short = await client.post("/api/v1/tenants", json={"name": "ز"}, headers=headers)

    assert blank.status_code == 422
    assert too_short.status_code == 422


async def test_workspace_creation_requires_authentication(client: AsyncClient) -> None:
    response = await client.post("/api/v1/tenants", json={"name": "متجر بلا هوية"})
    assert response.status_code == 401


async def test_workspace_creation_is_atomic_with_exactly_one_owner(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    """Onboarding is atomic: exactly one OWNER membership per created tenant."""
    email = f"atomic-{uuid.uuid4().hex[:10]}@example.com"
    registered = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": DEFAULT_PASSWORD, "full_name": "تاجر"},
    )
    created = await client.post(
        "/api/v1/tenants",
        json={"name": "متجر الإخلاص"},
        headers={"Authorization": f"Bearer {registered.json()['access_token']}"},
    )
    tenant_id = uuid.UUID(created.json()["tenant"]["id"])

    rows = (
        (await owner_session.execute(select(Membership).where(Membership.tenant_id == tenant_id)))
        .scalars()
        .all()
    )

    assert len(rows) == 1
    assert rows[0].role is MembershipRole.OWNER
    assert rows[0].status is MembershipStatus.ACTIVE

    tenant = await owner_session.get(Tenant, tenant_id)
    assert tenant is not None
