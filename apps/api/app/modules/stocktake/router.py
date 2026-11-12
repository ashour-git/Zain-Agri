"""Stocktake (جرد) routes. Every route needs ``inventory.adjust``: counts are
for the people who correct stock, not for cashiers."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.session import get_session
from app.modules.auth.dependencies import (
    Principal,
    TenantContext,
    get_current_principal,
    require_permission,
)
from app.modules.authorization.permissions import Permission
from app.modules.stocktake import service
from app.modules.stocktake.schemas import (
    ApplyOut,
    LineCount,
    LineListOut,
    LineOut,
    ReviewOut,
    StocktakeCreate,
    StocktakeListOut,
    StocktakeOut,
)

router = APIRouter(prefix="/api/v1/stocktakes", tags=["stocktake"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
PrincipalDep = Annotated[Principal, Depends(get_current_principal)]
Counter = Annotated[TenantContext, Depends(require_permission(Permission.INVENTORY_ADJUST))]


@router.post("", response_model=StocktakeOut, status_code=status.HTTP_201_CREATED)
async def start_stocktake(
    payload: StocktakeCreate, context: Counter, principal: PrincipalDep, db: SessionDep
) -> StocktakeOut:
    return await service.start(
        db, tenant_id=context.tenant.id, actor_id=principal.user_id, payload=payload
    )


@router.get("", response_model=StocktakeListOut)
async def list_stocktakes(context: Counter, db: SessionDep) -> StocktakeListOut:
    return await service.list_stocktakes(db, tenant_id=context.tenant.id)


@router.get("/{stocktake_id}", response_model=StocktakeOut)
async def get_stocktake(stocktake_id: uuid.UUID, context: Counter, db: SessionDep) -> StocktakeOut:
    return await service.get_stocktake(db, tenant_id=context.tenant.id, stocktake_id=stocktake_id)


@router.get("/{stocktake_id}/lines", response_model=LineListOut)
async def list_lines(
    stocktake_id: uuid.UUID,
    context: Counter,
    db: SessionDep,
    q: Annotated[str | None, Query(max_length=100)] = None,
    only_uncounted: bool = False,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> LineListOut:
    return await service.list_lines(
        db,
        tenant_id=context.tenant.id,
        stocktake_id=stocktake_id,
        q=q,
        only_uncounted=only_uncounted,
        page=page,
        page_size=page_size,
    )


@router.put("/{stocktake_id}/lines/{line_id}", response_model=LineOut)
async def count_line(
    stocktake_id: uuid.UUID,
    line_id: uuid.UUID,
    payload: LineCount,
    context: Counter,
    principal: PrincipalDep,
    db: SessionDep,
) -> LineOut:
    return await service.count_line(
        db,
        tenant_id=context.tenant.id,
        actor_id=principal.user_id,
        stocktake_id=stocktake_id,
        line_id=line_id,
        payload=payload,
    )


@router.get("/{stocktake_id}/review", response_model=ReviewOut)
async def review_stocktake(stocktake_id: uuid.UUID, context: Counter, db: SessionDep) -> ReviewOut:
    return await service.review(db, tenant_id=context.tenant.id, stocktake_id=stocktake_id)


@router.post("/{stocktake_id}/apply", response_model=ApplyOut)
async def apply_stocktake(
    stocktake_id: uuid.UUID, context: Counter, principal: PrincipalDep, db: SessionDep
) -> ApplyOut:
    return await service.apply(
        db, tenant_id=context.tenant.id, actor_id=principal.user_id, stocktake_id=stocktake_id
    )


@router.post("/{stocktake_id}/cancel", response_model=StocktakeOut)
async def cancel_stocktake(
    stocktake_id: uuid.UUID, context: Counter, principal: PrincipalDep, db: SessionDep
) -> StocktakeOut:
    return await service.cancel(
        db, tenant_id=context.tenant.id, actor_id=principal.user_id, stocktake_id=stocktake_id
    )
