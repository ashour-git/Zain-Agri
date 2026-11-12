import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.modules.stocktake.models import ShortageReason, StocktakeScope, StocktakeStatus


class StocktakeCreate(BaseModel):
    scope: StocktakeScope = StocktakeScope.ALL
    category_id: uuid.UUID | None = None
    name: str | None = Field(default=None, max_length=120)
    # Blind by default: the system quantity stays hidden until a line is counted.
    blind: bool = True

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str | None) -> str | None:
        cleaned = (value or "").strip()
        return cleaned or None


class StocktakeOut(BaseModel):
    id: uuid.UUID
    name: str
    scope: StocktakeScope
    category_id: uuid.UUID | None
    blind: bool
    status: StocktakeStatus
    created_at: datetime
    applied_at: datetime | None
    total_lines: int
    counted_lines: int


class StocktakeListOut(BaseModel):
    items: list[StocktakeOut]


class LineOut(BaseModel):
    line_id: uuid.UUID
    product_id: uuid.UUID
    sku: str
    barcode: str | None
    name_ar: str
    batch_id: uuid.UUID | None
    batch_number: str | None
    base_unit_id: uuid.UUID
    base_unit_name_ar: str
    counted_quantity: Decimal | None
    counted_unit_id: uuid.UUID | None
    counted_base_quantity: Decimal | None
    # None while the count is blind and the line has not been counted yet.
    system_quantity: Decimal | None
    shortage_reason: ShortageReason


class LineListOut(BaseModel):
    items: list[LineOut]
    total: int
    page: int
    page_size: int


class LineCount(BaseModel):
    quantity: Decimal = Field(ge=0, max_digits=18, decimal_places=4)
    # The unit the shelf was counted in; defaults to the product's base unit.
    unit_id: uuid.UUID | None = None
    shortage_reason: ShortageReason | None = None


class ReviewItem(BaseModel):
    line_id: uuid.UUID
    product_id: uuid.UUID
    name_ar: str
    batch_number: str | None
    base_unit_name_ar: str
    system_quantity_at_count: Decimal
    counted_base_quantity: Decimal
    difference: Decimal
    current_quantity: Decimal
    shortage_reason: ShortageReason


class UncountedItem(BaseModel):
    line_id: uuid.UUID
    product_id: uuid.UUID
    name_ar: str
    batch_number: str | None


class ReviewOut(BaseModel):
    shortages: list[ReviewItem]
    surpluses: list[ReviewItem]
    unchanged: int
    uncounted: list[UncountedItem]


class ApplyOut(BaseModel):
    corrections: int
