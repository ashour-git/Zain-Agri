"""Cryptographic primitives for authentication.

Nothing here touches the database. Passwords are Argon2id hashes, access tokens
are short-lived HS256 JWTs, refresh tokens are opaque random strings whose
SHA-256 digest is the only thing persisted.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2 import Type as Argon2Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import Settings
from app.modules.identity.models import MembershipRole

ACCESS_TOKEN_KIND = "access"  # noqa: S105 - a JWT "typ" marker, not a credential

# Verified against when the email is unknown, so a missing user and a wrong
# password take the same amount of time. Built lazily because hashing is
# deliberately expensive.
_DUMMY_HASHES: dict[tuple[int, int, int], str] = {}


def _hasher(settings: Settings) -> PasswordHasher:
    return PasswordHasher(
        type=Argon2Type.ID,
        time_cost=settings.argon2_time_cost,
        memory_cost=settings.argon2_memory_cost,
        parallelism=settings.argon2_parallelism,
        hash_len=32,
        salt_len=16,
    )


def hash_password(password: str, settings: Settings) -> str:
    return _hasher(settings).hash(password)


def verify_password(password: str, password_hash: str, settings: Settings) -> bool:
    try:
        return _hasher(settings).verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def dummy_verify(password: str, settings: Settings) -> None:
    """Burn the same CPU time as a real verification for unknown accounts."""
    key = (settings.argon2_time_cost, settings.argon2_memory_cost, settings.argon2_parallelism)
    password_hash = _DUMMY_HASHES.get(key)
    if password_hash is None:
        password_hash = hash_password(secrets.token_urlsafe(16), settings)
        _DUMMY_HASHES[key] = password_hash
    verify_password(password, password_hash, settings)


def password_needs_rehash(password_hash: str, settings: Settings) -> bool:
    try:
        return _hasher(settings).check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def generate_refresh_token() -> str:
    """48 random bytes, URL-safe. ~64 characters."""
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    """SHA-256 is enough: the token is 384 bits of entropy, not a password."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_access_token(
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    tenant_id: uuid.UUID | None,
    role: MembershipRole | None,
    settings: Settings,
) -> tuple[str, int]:
    now = datetime.now(UTC)
    ttl = timedelta(minutes=settings.access_token_ttl_minutes)
    expires_at = now + ttl

    payload: dict[str, Any] = {
        "sub": str(user_id),
        "sid": str(session_id),
        "typ": ACCESS_TOKEN_KIND,
        "jti": secrets.token_hex(16),
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "tid": str(tenant_id) if tenant_id else None,
        "rol": role.value if role else None,
    }

    token = jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    return token, int(ttl.total_seconds())


def decode_access_token(token: str, settings: Settings) -> dict[str, Any]:
    """Raises jwt.InvalidTokenError for anything that is not a valid access token."""
    claims: dict[str, Any] = jwt.decode(
        token,
        settings.jwt_secret_key.get_secret_value(),
        algorithms=[settings.jwt_algorithm],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
        options={"require": ["exp", "iat", "sub", "sid", "iss", "aud"]},
    )
    if claims.get("typ") != ACCESS_TOKEN_KIND:
        raise jwt.InvalidTokenError("not an access token")
    return claims
