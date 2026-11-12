import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class ColumnOut(BaseModel):
    index: int
    header: str
    samples: list[str]
    field: str | None
    source: Literal["rules", "ai"] | None


class AnalyzeOut(BaseModel):
    sheet_names: list[str]
    sheet: str
    header_row: int  # 1-based sheet row number
    first_data_row: int  # 1-based sheet row number of rows[0]
    columns: list[ColumnOut]
    rows: list[list[str]]
    assistant_available: bool
    assistant_used: bool


class ImportRequest(BaseModel):
    # Column index -> product field. Validated against the fixed field list.
    mapping: dict[int, str]
    rows: list[list[str]]
    first_row_number: int = Field(default=2, ge=1)
    default_unit_id: uuid.UUID | None = None
    create_categories: bool = True
    create_brands: bool = True
    skip_errors: bool = False


class PreviewRow(BaseModel):
    row_number: int
    status: Literal["create", "skip", "error"]
    reason_ar: str | None
    warnings: list[str]
    name_ar: str | None
    sku: str | None
    unit_name_ar: str | None
    quantity: Decimal | None
    sale_price: Decimal | None


class PreviewCounts(BaseModel):
    create: int
    skip: int
    error: int


class PreviewOut(BaseModel):
    counts: PreviewCounts
    ignored_blank: int
    rows: list[PreviewRow]
    new_categories: list[str]
    new_brands: list[str]
    notices: list[str]


class CommitOut(BaseModel):
    created: int
    skipped: int
    opening_balances: int
    new_categories: int
    new_brands: int
