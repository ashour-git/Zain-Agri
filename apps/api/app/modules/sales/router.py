"""Sales routes."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.session import get_session
from app.modules.auth.dependencies import CurrentPrincipal, TenantContext, require_permission
from app.modules.authorization.permissions import Permission
from app.modules.sales import service
from app.modules.sales.schemas import SaleIn, SaleOut

router = APIRouter(prefix="/api/v1/sales", tags=["sales"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
Seller = Annotated[TenantContext, Depends(require_permission(Permission.SALES_OPERATE))]


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


@router.get("/{invoice_id}", response_model=SaleOut)
async def get_sale(invoice_id: uuid.UUID, context: Seller, db: SessionDep) -> SaleOut:
    return await service.get_sale(db, context.tenant.id, invoice_id)
