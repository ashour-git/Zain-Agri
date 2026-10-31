"""Authentication request and response contracts."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.modules.authorization.permissions import Permission
from app.modules.identity.models import MembershipRole, MembershipStatus, TenantStatus

_BLOCKED_PASSWORDS = {
    "password",
    "password1",
    "password123",
    "1234567890",
    "123456789012",
    "qwertyuiop",
    "administrator",
}


def _validate_password(value: str) -> str:
    if value.lower() in _BLOCKED_PASSWORDS:
        raise ValueError("password is too common")
    if value.isdigit():
        raise ValueError("password must not be only digits")
    return value


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    full_name: str = Field(min_length=2, max_length=200)

    _check_password = field_validator("password")(_validate_password)


class LoginRequest(BaseModel):
    email: EmailStr
    # No minimum length here: a short password must fail as invalid
    # credentials, not as a validation error that reveals the policy.
    password: str = Field(min_length=1, max_length=128)
    tenant_id: uuid.UUID | None = None


class RefreshRequest(BaseModel):
    tenant_id: uuid.UUID | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str
    is_active: bool
    email_verified_at: datetime | None
    created_at: datetime


class TenantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    status: TenantStatus
    created_at: datetime


class TenantMembershipOut(BaseModel):
    """A tenant the current user can enter, with the role inside it."""

    id: uuid.UUID
    name: str
    slug: str
    status: TenantStatus
    role: MembershipRole
    membership_status: MembershipStatus


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - an RFC 6750 scheme name
    expires_in: int
    user: UserOut
    tenant: TenantOut | None = None
    role: MembershipRole | None = None
    permissions: list[Permission] = []
    tenants: list[TenantMembershipOut] = []
    requires_tenant_selection: bool = False


class MeResponse(BaseModel):
    user: UserOut
    tenant: TenantOut | None = None
    role: MembershipRole | None = None
    permissions: list[Permission] = []
    tenants: list[TenantMembershipOut] = []
    requires_tenant_selection: bool = False


class SessionOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    expires_at: datetime
    user_agent: str | None
    is_current: bool


class CreateTenantRequest(BaseModel):
    name: str = Field(min_length=2, max_length=200)

    @field_validator("name")
    @classmethod
    def _strip(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned


class CreateTenantResponse(BaseModel):
    tenant: TenantOut
    role: MembershipRole
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - an RFC 6750 scheme name
    expires_in: int
    permissions: list[Permission]


class MessageResponse(BaseModel):
    message: str


class UpdateTenantRequest(BaseModel):
    name: str = Field(min_length=2, max_length=200)

    @field_validator("name")
    @classmethod
    def _strip(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned


class TenantMemberOut(BaseModel):
    """A colleague inside the current tenant. Never exposes hashes."""

    membership_id: uuid.UUID
    user_id: uuid.UUID
    email: EmailStr
    full_name: str
    role: MembershipRole
    status: MembershipStatus
    is_active: bool
    created_at: datetime
