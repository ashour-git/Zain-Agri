"""Inventory API: balances, ledger, adjustments and batches.

Route order matters: the static ``/movements``, ``/batches`` and
``/adjustments`` paths are declared before ``/{product_id}`` so they are never
interpreted as a product UUID.
"""

import uuid
from datetime import datetime
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
from app.modules.catalog.schemas import StockStatus
from app.modules.inventory import service
from app.modules.inventory.models import StockMovementType
from app.modules.inventory.schemas import (
    AdjustmentOut,
    AdjustmentRequest,
    BatchCreate,
    BatchListOut,
    BatchOut,
    InventoryDetailOut,
    InventoryListOut,
    MovementListOut,
)

router = APIRouter(prefix="/api/v1/inventory", tags=["inventory"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
PrincipalDep = Annotated[Principal, Depends(get_current_principal)]

InventoryReader = Annotated[TenantContext, Depends(require_permission(Permission.INVENTORY_READ))]
InventoryAdjuster = Annotated[
    TenantContext, Depends(require_permission(Permission.INVENTORY_ADJUST))
]
BatchesManager = Annotated[TenantContext, Depends(require_permission(Permission.BATCHES_MANAGE))]

Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


@router.get("", response_model=InventoryListOut)
async def list_inventory(
    context: InventoryReader,
    db: SessionDep,
    page: Page = 1,
    page_size: PageSize = 25,
    q: Annotated[str | None, Query(max_length=100)] = None,
    category_id: uuid.UUID | None = None,
    stock: StockStatus | None = None,
) -> InventoryListOut:
    return await service.list_inventory(
        db,
        tenant_id=context.tenant.id,
        page=page,
        page_size=page_size,
        q=q,
        category_id=category_id,
        stock=stock,
    )


@router.get("/movements", response_model=MovementListOut)
async def list_movements(
    context: InventoryReader,
    db: SessionDep,
    page: Page = 1,
    page_size: PageSize = 25,
    product_id: uuid.UUID | None = None,
    movement_type: StockMovementType | None = None,
    batch_id: uuid.UUID | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> MovementListOut:
    return await service.list_movements(
        db,
        tenant_id=context.tenant.id,
        page=page,
        page_size=page_size,
        product_id=product_id,
        movement_type=movement_type,
        batch_id=batch_id,
        created_from=created_from,
        created_to=created_to,
        view_cost=context.allows(Permission.INVENTORY_VIEW_COST),
    )


@router.post("/adjustments", response_model=AdjustmentOut, status_code=status.HTTP_201_CREATED)
async def create_adjustment(
    payload: AdjustmentRequest,
    context: InventoryAdjuster,
    principal: PrincipalDep,
    db: SessionDep,
) -> AdjustmentOut:
    return await service.record_movement(
        db, context=context, actor_id=principal.user_id, payload=payload
    )


@router.get("/batches", response_model=BatchListOut)
async def list_batches(
    context: InventoryReader,
    db: SessionDep,
    page: Page = 1,
    page_size: PageSize = 25,
    product_id: uuid.UUID | None = None,
    q: Annotated[str | None, Query(max_length=80)] = None,
) -> BatchListOut:
    return await service.list_batches(
        db,
        tenant_id=context.tenant.id,
        page=page,
        page_size=page_size,
        product_id=product_id,
        q=q,
    )


@router.post("/batches", response_model=BatchOut, status_code=status.HTTP_201_CREATED)
async def create_batch(
    payload: BatchCreate,
    context: BatchesManager,
    principal: PrincipalDep,
    db: SessionDep,
) -> BatchOut:
    return await service.create_batch(
        db, context=context, actor_id=principal.user_id, payload=payload
    )


@router.get("/{product_id}", response_model=InventoryDetailOut)
async def get_inventory_detail(
    product_id: uuid.UUID,
    context: InventoryReader,
    db: SessionDep,
) -> InventoryDetailOut:
    return await service.get_inventory_detail(
        db,
        tenant_id=context.tenant.id,
        product_id=product_id,
        view_cost=context.allows(Permission.INVENTORY_VIEW_COST),
    )
