"""Customers: create, update, list with balances, statement, payments, corrections."""

import re
import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnprocessableError,
)
from app.core.money import money
from app.modules.audit import service as audit
from app.modules.auth.dependencies import TenantContext
from app.modules.authorization.permissions import Permission
from app.modules.catalog.service import _escape_like
from app.modules.customers.ledger import balance, post_entry
from app.modules.customers.models import Customer, CustomerLedgerEntry, LedgerKind
from app.modules.customers.schemas import (
    CorrectionIn,
    CustomerCreate,
    CustomerListOut,
    CustomerOut,
    CustomerUpdate,
    PaymentIn,
    StatementLineOut,
    StatementOut,
)
from app.modules.identity.models import User
from app.modules.importer.normalize import normalize_name

NOT_FOUND = "Customer not found"
DUPLICATE = "A customer with this name already exists"
BAD_PHONE = "Enter an Egyptian mobile number"
NO_ADJUST = "Your role cannot change customer balances"

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_EGYPT_MOBILE = re.compile(r"^(?:\+?20|0020)?0?(1[0125]\d{8})$")


def normalize_phone(raw: str) -> str:
    """An Egyptian mobile as +201XXXXXXXXX; ValueError for anything else."""
    digits = re.sub(r"[\s\-()]", "", raw.translate(_ARABIC_DIGITS))
    match = _EGYPT_MOBILE.match(digits)
    if match is None:
        raise ValueError(BAD_PHONE)
    return f"+20{match.group(1)}"


def _phone_or_error(raw: str | None) -> str | None:
    if raw is None or not raw.strip():
        return None
    try:
        return normalize_phone(raw)
    except ValueError as exc:
        raise UnprocessableError(BAD_PHONE) from exc


def _out(customer: Customer, amount: Decimal) -> CustomerOut:
    return CustomerOut(
        id=customer.id,
        name=customer.name,
        phone=customer.phone,
        active=customer.active,
        balance=amount,
    )


async def get_customer(db: AsyncSession, tenant_id: uuid.UUID, customer_id: uuid.UUID) -> Customer:
    customer = await db.scalar(
        select(Customer).where(Customer.id == customer_id, Customer.tenant_id == tenant_id)
    )
    if customer is None:
        raise NotFoundError(NOT_FOUND)
    return customer


async def create_customer(
    db: AsyncSession, context: TenantContext, actor_id: uuid.UUID, payload: CustomerCreate
) -> CustomerOut:
    tenant_id = context.tenant.id
    opening = money(payload.opening_balance) if payload.opening_balance is not None else None
    if opening and not context.allows(Permission.CUSTOMERS_ADJUST):
        raise ForbiddenError(NO_ADJUST, details={"permission": Permission.CUSTOMERS_ADJUST.value})

    customer = Customer(
        tenant_id=tenant_id,
        name=payload.name,
        name_key=normalize_name(payload.name),
        phone=_phone_or_error(payload.phone),
        active=True,
        created_by=actor_id,
    )
    db.add(customer)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError(DUPLICATE) from exc

    if opening:
        await post_entry(
            db,
            tenant_id=tenant_id,
            customer_id=customer.id,
            kind=LedgerKind.OPENING,
            amount=opening,
            actor_id=actor_id,
            note="رصيد سابق",
        )
    await audit.record(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="customer.created",
        entity_type="customer",
        entity_id=customer.id,
        after_state={"name": customer.name, "opening_balance": opening},
    )
    await db.commit()
    return _out(customer, opening or Decimal("0.00"))


async def update_customer(
    db: AsyncSession,
    context: TenantContext,
    actor_id: uuid.UUID,
    customer_id: uuid.UUID,
    payload: CustomerUpdate,
) -> CustomerOut:
    tenant_id = context.tenant.id
    customer = await get_customer(db, tenant_id, customer_id)
    before = {"name": customer.name, "phone": customer.phone, "active": customer.active}
    if payload.name is not None:
        customer.name = payload.name
        customer.name_key = normalize_name(payload.name)
    if "phone" in payload.model_fields_set:
        customer.phone = _phone_or_error(payload.phone)
    if payload.active is not None:
        customer.active = payload.active
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError(DUPLICATE) from exc
    await audit.record(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="customer.updated",
        entity_type="customer",
        entity_id=customer.id,
        before_state=before,
        after_state={"name": customer.name, "phone": customer.phone, "active": customer.active},
    )
    await db.commit()
    return _out(customer, await balance(db, tenant_id, customer.id))


async def list_customers(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    q: str | None,
    owes: bool,
    include_inactive: bool,
    page: int,
    page_size: int,
) -> CustomerListOut:
    owed = (
        select(
            CustomerLedgerEntry.customer_id.label("customer_id"),
            func.sum(CustomerLedgerEntry.amount).label("balance"),
        )
        .where(CustomerLedgerEntry.tenant_id == tenant_id)
        .group_by(CustomerLedgerEntry.customer_id)
        .subquery()
    )
    amount = func.coalesce(owed.c.balance, 0)
    query = (
        select(Customer, amount)
        .outerjoin(owed, owed.c.customer_id == Customer.id)
        .where(Customer.tenant_id == tenant_id)
    )
    if not include_inactive:
        query = query.where(Customer.active.is_(True))
    if owes:
        query = query.where(amount > 0)
    if q and q.strip():
        pattern = f"%{_escape_like(q.strip())}%"
        query = query.where(
            Customer.name.ilike(pattern, escape="\\") | Customer.phone.ilike(pattern, escape="\\")
        )
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = (
        await db.execute(
            query.order_by(amount.desc(), Customer.name)
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
    ).all()
    return CustomerListOut(
        items=[_out(customer, money(Decimal(value))) for customer, value in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


async def statement(
    db: AsyncSession, *, tenant_id: uuid.UUID, customer_id: uuid.UUID
) -> StatementOut:
    customer = await get_customer(db, tenant_id, customer_id)
    rows = (
        await db.execute(
            select(CustomerLedgerEntry, User.full_name)
            .outerjoin(User, User.id == CustomerLedgerEntry.created_by)
            .where(
                CustomerLedgerEntry.tenant_id == tenant_id,
                CustomerLedgerEntry.customer_id == customer_id,
            )
            .order_by(CustomerLedgerEntry.created_at, CustomerLedgerEntry.id)
        )
    ).all()
    running = Decimal("0.00")
    lines: list[StatementLineOut] = []
    for entry, actor in rows:
        running = money(running + entry.amount)
        lines.append(
            StatementLineOut(
                id=entry.id,
                kind=LedgerKind(entry.kind),
                amount=money(entry.amount),
                balance_after=running,
                reference_type=entry.reference_type,
                reference_id=entry.reference_id,
                note=entry.note,
                created_at=entry.created_at,
                created_by_name=actor,
            )
        )
    return StatementOut(customer=_out(customer, running), lines=lines, balance=running)


async def record_payment(
    db: AsyncSession,
    context: TenantContext,
    actor_id: uuid.UUID,
    customer_id: uuid.UUID,
    payload: PaymentIn,
) -> CustomerOut:
    tenant_id = context.tenant.id
    customer = await get_customer(db, tenant_id, customer_id)
    entry = await post_entry(
        db,
        tenant_id=tenant_id,
        customer_id=customer.id,
        kind=LedgerKind.PAYMENT,
        amount=-payload.amount,
        actor_id=actor_id,
        note=payload.note,
    )
    await audit.record(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="customer.payment",
        entity_type="customer",
        entity_id=customer.id,
        after_state={"amount": payload.amount, "ledger_id": entry.id},
    )
    await db.commit()
    return _out(customer, await balance(db, tenant_id, customer.id))


async def record_correction(
    db: AsyncSession,
    context: TenantContext,
    actor_id: uuid.UUID,
    customer_id: uuid.UUID,
    payload: CorrectionIn,
) -> CustomerOut:
    tenant_id = context.tenant.id
    customer = await get_customer(db, tenant_id, customer_id)
    entry = await post_entry(
        db,
        tenant_id=tenant_id,
        customer_id=customer.id,
        kind=LedgerKind.CORRECTION,
        amount=payload.amount,
        actor_id=actor_id,
        note=payload.reason,
    )
    await audit.record(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="customer.correction",
        entity_type="customer",
        entity_id=customer.id,
        after_state={"amount": payload.amount, "ledger_id": entry.id},
        meta={"reason": payload.reason},
    )
    await db.commit()
    return _out(customer, await balance(db, tenant_id, customer.id))
