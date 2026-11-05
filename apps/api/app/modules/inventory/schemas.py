"""Inventory contracts: stock view, ledger, adjustments, batches."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.modules.catalog.models import ProductStatus
from app.modules.catalog.schemas import StockStatus
from app.modules.inventory.models import IMPLEMENTED_MOVEMENT_TYPES, StockMovementType

MovementDirection = Literal["in", "out"]

MAX_REASON_LENGTH = 500


class InventoryItemOut(BaseModel):
    product_id: uuid.UUID
    sku: str
    name_ar: str
    name: str | None
    category_id: uuid.UUID | None
    category_name: str | None
    base_unit_id: uuid.UUID
    base_unit_code: str
    base_unit_name_ar: str
    quantity: Decimal
    minimum_stock: Decimal
    stock_status: StockStatus
    tracks_batches: bool
    product_status: ProductStatus
    sale_price: Decimal | None
    updated_at: datetime | None


class InventoryListOut(BaseModel):
    items: list[InventoryItemOut]
    total: int
    page: int
    page_size: int


class MovementOut(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    product_name_ar: str
    batch_id: uuid.UUID | None
    batch_number: str | None
    movement_type: StockMovementType
    direction: MovementDirection
    quantity: Decimal
    unit_id: uuid.UUID
    unit_code: str
    unit_name_ar: str
    base_quantity: Decimal
    # Per base unit. Null unless the caller holds inventory.view_cost.
    unit_cost: Decimal | None
    notes: str | None
    created_by: uuid.UUID | None
    created_by_name: str | None
    created_at: datetime


class MovementListOut(BaseModel):
    items: list[MovementOut]
    total: int
    page: int
    page_size: int


class AdjustmentRequest(BaseModel):
    product_id: uuid.UUID
    movement_type: StockMovementType
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=4)
    unit_id: uuid.UUID
    batch_id: uuid.UUID | None = None
    reason: str = Field(min_length=3, max_length=MAX_REASON_LENGTH)
    unit_cost: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)

    @field_validator("movement_type")
    @classmethod
    def _implemented_type(cls, value: StockMovementType) -> StockMovementType:
        if value not in IMPLEMENTED_MOVEMENT_TYPES:
            raise ValueError(f"{value.value} is not writable yet")
        return value

    @field_validator("reason")
    @classmethod
    def _clean_reason(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 3:
            raise ValueError("reason is too short")
        return cleaned


class AdjustmentOut(BaseModel):
    movement: MovementOut
    balance_before: Decimal
    balance_after: Decimal


class BatchOut(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    product_name_ar: str
    batch_number: str
    expiry_date: date | None
    quantity: Decimal
    created_at: datetime


class BatchListOut(BaseModel):
    items: list[BatchOut]
    total: int
    page: int
    page_size: int


class BatchCreate(BaseModel):
    product_id: uuid.UUID
    batch_number: str = Field(min_length=1, max_length=80)
    expiry_date: date | None = None

    @field_validator("batch_number")
    @classmethod
    def _clean_number(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("batch_number must not be blank")
        return cleaned


class InventoryDetailOut(BaseModel):
    product: InventoryItemOut
    batches: list[BatchOut]
    movements: list[MovementOut]
