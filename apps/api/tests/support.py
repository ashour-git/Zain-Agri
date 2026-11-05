"""Fixture builders shared by the Sprint 02 suites.

Rows are created through the *owner* session so that seeding is not subject to
RLS. Anything the tests then read goes through the runtime role.
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.auth.security import hash_password
from app.modules.catalog.models import Product, ProductCategory, ProductStatus
from app.modules.identity.models import (
    Membership,
    MembershipRole,
    MembershipStatus,
    Tenant,
    TenantStatus,
    User,
)
from app.modules.inventory.models import ProductBatch

DEFAULT_PASSWORD = "ZainAgri!2026"
BROWSER_ORIGIN = "http://localhost:3000"

# Seeded by migration 0004. Units are global reference data.
UNIT_IDS: dict[str, uuid.UUID] = {
    "piece": uuid.UUID("0192f000-0000-4000-8000-000000000001"),
    "kilogram": uuid.UUID("0192f000-0000-4000-8000-000000000002"),
    "gram": uuid.UUID("0192f000-0000-4000-8000-000000000003"),
    "liter": uuid.UUID("0192f000-0000-4000-8000-000000000004"),
    "milliliter": uuid.UUID("0192f000-0000-4000-8000-000000000005"),
    "bag": uuid.UUID("0192f000-0000-4000-8000-000000000006"),
    "bottle": uuid.UUID("0192f000-0000-4000-8000-000000000007"),
    "box": uuid.UUID("0192f000-0000-4000-8000-000000000008"),
    "pack": uuid.UUID("0192f000-0000-4000-8000-000000000009"),
}


def unit_id(code: str) -> uuid.UUID:
    return UNIT_IDS[code]


async def make_user(
    session: AsyncSession,
    *,
    email: str | None = None,
    password: str = DEFAULT_PASSWORD,
    full_name: str = "مستخدم اختبار",
    is_active: bool = True,
) -> User:
    user = User(
        email=email or f"user-{uuid.uuid4().hex[:12]}@example.com",
        password_hash=hash_password(password, get_settings()),
        full_name=full_name,
        is_active=is_active,
        email_verified_at=datetime.now(UTC),
    )
    session.add(user)
    await session.flush()
    return user


async def make_tenant(
    session: AsyncSession,
    *,
    name: str = "متجر زين",
    status: TenantStatus = TenantStatus.ACTIVE,
) -> Tenant:
    tenant = Tenant(name=name, slug=f"t-{uuid.uuid4().hex[:12]}", status=status)
    session.add(tenant)
    await session.flush()
    return tenant


async def make_membership(
    session: AsyncSession,
    *,
    tenant: Tenant,
    user: User,
    role: MembershipRole = MembershipRole.OWNER,
    status: MembershipStatus = MembershipStatus.ACTIVE,
) -> Membership:
    membership = Membership(tenant_id=tenant.id, user_id=user.id, role=role, status=status)
    session.add(membership)
    await session.flush()
    return membership


async def seed_member(
    session: AsyncSession,
    *,
    role: MembershipRole = MembershipRole.OWNER,
    tenant_status: TenantStatus = TenantStatus.ACTIVE,
    membership_status: MembershipStatus = MembershipStatus.ACTIVE,
    password: str = DEFAULT_PASSWORD,
    tenant_name: str = "متجر زين",
) -> tuple[User, Tenant, Membership]:
    """A committed user with exactly one workspace, ready to log into."""
    user = await make_user(session, password=password)
    tenant = await make_tenant(session, name=tenant_name, status=tenant_status)
    membership = await make_membership(
        session, tenant=tenant, user=user, role=role, status=membership_status
    )
    await session.commit()
    return user, tenant, membership


async def login(
    client: AsyncClient,
    email: str,
    password: str = DEFAULT_PASSWORD,
    tenant_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"email": email, "password": password}
    if tenant_id is not None:
        payload["tenant_id"] = str(tenant_id)
    response = await client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def auth_header(body: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {body['access_token']}"}


async def seeded_login(
    client: AsyncClient,
    session: AsyncSession,
    *,
    role: MembershipRole = MembershipRole.OWNER,
    tenant_name: str = "متجر زين",
) -> tuple[dict[str, Any], dict[str, str], Tenant, User]:
    """Create a user + workspace, log in, and return the auth pieces."""
    user, tenant, _ = await seed_member(session, role=role, tenant_name=tenant_name)
    body = await login(client, user.email)
    return body, auth_header(body), tenant, user


# --- catalog and inventory --------------------------------------------------


def product_payload(
    *,
    sku: str | None = None,
    name_ar: str = "بذور طماطم هجين",
    base_unit: str = "piece",
    **overrides: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "sku": sku or f"SKU-{uuid.uuid4().hex[:10].upper()}",
        "name_ar": name_ar,
        "base_unit_id": str(unit_id(base_unit)),
        "sale_price": "25.00",
        "minimum_stock": "5",
    }
    payload.update(overrides)
    return payload


async def create_product_api(
    client: AsyncClient, headers: dict[str, str], **overrides: Any
) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/products", json=product_payload(**overrides), headers=headers
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def adjust_api(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    product_id: str,
    movement_type: str = "opening_balance",
    quantity: str = "10",
    unit_code: str = "piece",
    reason: str = "رصيد افتتاحي",
    batch_id: str | None = None,
    unit_cost: str | None = None,
    expected: int = 201,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "product_id": product_id,
        "movement_type": movement_type,
        "quantity": quantity,
        "unit_id": str(unit_id(unit_code)),
        "reason": reason,
    }
    if batch_id is not None:
        payload["batch_id"] = batch_id
    if unit_cost is not None:
        payload["unit_cost"] = unit_cost
    response = await client.post("/api/v1/inventory/adjustments", json=payload, headers=headers)
    assert response.status_code == expected, response.text
    body: dict[str, Any] = response.json()
    return body


async def make_category(
    session: AsyncSession, tenant: Tenant, *, name: str = "بذور", parent_id: uuid.UUID | None = None
) -> ProductCategory:
    category = ProductCategory(tenant_id=tenant.id, name=name, name_ar=name, parent_id=parent_id)
    session.add(category)
    await session.flush()
    return category


async def make_product_row(
    session: AsyncSession,
    tenant: Tenant,
    *,
    sku: str | None = None,
    name_ar: str = "بذور طماطم هجين",
    base_unit: str = "piece",
    tracks_batches: bool = False,
    category_id: uuid.UUID | None = None,
    cost_price: Decimal | None = None,
) -> Product:
    product = Product(
        tenant_id=tenant.id,
        sku=sku or f"SKU-{uuid.uuid4().hex[:10].upper()}",
        name_ar=name_ar,
        base_unit_id=unit_id(base_unit),
        tracks_batches=tracks_batches,
        category_id=category_id,
        cost_price=cost_price,
        sale_price=Decimal("25.00"),
        minimum_stock=Decimal("5"),
        status=ProductStatus.ACTIVE,
    )
    session.add(product)
    await session.flush()
    return product


async def make_batch_row(
    session: AsyncSession,
    tenant: Tenant,
    product: Product,
    *,
    batch_number: str | None = None,
    expiry_date: date | None = None,
) -> ProductBatch:
    batch = ProductBatch(
        tenant_id=tenant.id,
        product_id=product.id,
        batch_number=batch_number or f"B-{uuid.uuid4().hex[:8]}",
        expiry_date=expiry_date,
    )
    session.add(batch)
    await session.flush()
    return batch
