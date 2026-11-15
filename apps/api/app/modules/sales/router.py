"""Sales routes."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.infrastructure.db.session import get_session
from app.modules.auth.dependencies import CurrentPrincipal, TenantContext, require_permission
from app.modules.authorization.permissions import Permission
from app.modules.sales import returns, service, sharing
from app.modules.sales.schemas import (
    ReturnIn,
    ReturnOut,
    SaleIn,
    SaleListOut,
    SaleOut,
    ShareOut,
)

router = APIRouter(prefix="/api/v1/sales", tags=["sales"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
Seller = Annotated[TenantContext, Depends(require_permission(Permission.SALES_OPERATE))]
Refunder = Annotated[TenantContext, Depends(require_permission(Permission.SALES_REFUND))]
Supervisor = Annotated[TenantContext, Depends(require_permission(Permission.SALES_DISCOUNT))]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.post("", response_model=SaleOut, status_code=status.HTTP_201_CREATED)
async def create_sale(
    payload: SaleIn,
    response: Response,
    context: Seller,
    principal: CurrentPrincipal,
    db: SessionDep,
) -> SaleOut:
    sale, created = await service.create_sale(db, context, principal.user_id, payload)
    if not created:
        # The same request again (double tap, retry): the first invoice.
        response.status_code = status.HTTP_200_OK
    return sale


@router.get("", response_model=SaleListOut)
async def list_sales(
    context: Seller,
    principal: CurrentPrincipal,
    db: SessionDep,
    q: Annotated[str | None, Query(max_length=100)] = None,
    customer_id: uuid.UUID | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> SaleListOut:
    return await service.list_sales(
        db,
        context,
        principal.user_id,
        q=q,
        customer_id=customer_id,
        page=page,
        page_size=page_size,
    )


@router.get("/{invoice_id}", response_model=SaleOut)
async def get_sale(
    invoice_id: uuid.UUID, context: Seller, principal: CurrentPrincipal, db: SessionDep
) -> SaleOut:
    return await service.get_visible_sale(db, context, principal.user_id, invoice_id)


@router.post("/{invoice_id}/returns", response_model=ReturnOut, status_code=status.HTTP_201_CREATED)
async def create_return(
    invoice_id: uuid.UUID,
    payload: ReturnIn,
    context: Refunder,
    principal: CurrentPrincipal,
    db: SessionDep,
) -> ReturnOut:
    return await returns.create_return(db, context, principal.user_id, invoice_id, payload)


@router.post("/{invoice_id}/share", response_model=ShareOut)
async def share_invoice(
    invoice_id: uuid.UUID,
    context: Seller,
    principal: CurrentPrincipal,
    settings: SettingsDep,
    db: SessionDep,
) -> ShareOut:
    return await sharing.share(db, context, principal.user_id, invoice_id, settings)


@router.delete("/{invoice_id}/share", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invoice_link(
    invoice_id: uuid.UUID, context: Supervisor, db: SessionDep
) -> Response:
    await sharing.revoke(db, context, invoice_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
