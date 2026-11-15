"""Customer routes. Selling roles (sales.operate) see customers, add them and
record payments; balance changes and edits need customers.adjust."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.session import get_session
from app.modules.auth.dependencies import CurrentPrincipal, TenantContext, require_permission
from app.modules.authorization.permissions import Permission
from app.modules.customers import service
from app.modules.customers.schemas import (
    CorrectionIn,
    CustomerCreate,
    CustomerListOut,
    CustomerOut,
    CustomerUpdate,
    PaymentIn,
    StatementOut,
)

router = APIRouter(prefix="/api/v1/customers", tags=["customers"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
Seller = Annotated[TenantContext, Depends(require_permission(Permission.SALES_OPERATE))]
Adjuster = Annotated[TenantContext, Depends(require_permission(Permission.CUSTOMERS_ADJUST))]


@router.get("", response_model=CustomerListOut)
async def list_customers(
    context: Seller,
    db: SessionDep,
    q: Annotated[str | None, Query(max_length=100)] = None,
    owes: bool = False,
    include_inactive: bool = False,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> CustomerListOut:
    return await service.list_customers(
        db,
        tenant_id=context.tenant.id,
        q=q,
        owes=owes,
        include_inactive=include_inactive,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=CustomerOut, status_code=status.HTTP_201_CREATED)
async def create_customer(
    payload: CustomerCreate, context: Seller, principal: CurrentPrincipal, db: SessionDep
) -> CustomerOut:
    return await service.create_customer(db, context, principal.user_id, payload)


@router.patch("/{customer_id}", response_model=CustomerOut)
async def update_customer(
    customer_id: uuid.UUID,
    payload: CustomerUpdate,
    context: Adjuster,
    principal: CurrentPrincipal,
    db: SessionDep,
) -> CustomerOut:
    return await service.update_customer(db, context, principal.user_id, customer_id, payload)


@router.get("/{customer_id}/statement", response_model=StatementOut)
async def customer_statement(
    customer_id: uuid.UUID, context: Seller, db: SessionDep
) -> StatementOut:
    return await service.statement(db, tenant_id=context.tenant.id, customer_id=customer_id)


@router.post(
    "/{customer_id}/payments", response_model=CustomerOut, status_code=status.HTTP_201_CREATED
)
async def record_payment(
    customer_id: uuid.UUID,
    payload: PaymentIn,
    context: Seller,
    principal: CurrentPrincipal,
    db: SessionDep,
) -> CustomerOut:
    return await service.record_payment(db, context, principal.user_id, customer_id, payload)


@router.post(
    "/{customer_id}/corrections", response_model=CustomerOut, status_code=status.HTTP_201_CREATED
)
async def record_correction(
    customer_id: uuid.UUID,
    payload: CorrectionIn,
    context: Adjuster,
    principal: CurrentPrincipal,
    db: SessionDep,
) -> CustomerOut:
    return await service.record_correction(db, context, principal.user_id, customer_id, payload)
