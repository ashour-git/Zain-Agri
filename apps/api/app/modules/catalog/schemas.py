"""Catalog request and response contracts.

Money and quantities are ``Decimal`` on the wire. Pydantic v2 serialises them as
JSON strings, which is exactly what the frontend wants: no binary floating point
ever touches a price.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.catalog.models import ProductStatus, UnitDimension

StockStatus = Literal["out", "low", "ok"]


def _strip(value: str) -> str:
    return value.strip()


class UnitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    name_ar: str
    dimension: UnitDimension


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    name_ar: str | None
    parent_id: uuid.UUID | None
    created_at: datetime


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    name_ar: str | None = Field(default=None, max_length=120)
    parent_id: uuid.UUID | None = None

    @field_validator("name", mode="after")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        return _strip(value)

    @field_validator("name_ar", mode="after")
    @classmethod
    def _clean_name_ar(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    name_ar: str | None = Field(default=None, max_length=120)
    parent_id: uuid.UUID | None = None

    @field_validator("name", mode="after")
    @classmethod
    def _clean_name(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("name_ar", mode="after")
    @classmethod
    def _clean_name_ar(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class BrandOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    name_ar: str | None
    created_at: datetime


class BrandCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    name_ar: str | None = Field(default=None, max_length=120)

    @field_validator("name", mode="after")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        return _strip(value)

    @field_validator("name_ar", mode="after")
    @classmethod
    def _clean_name_ar(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ConversionOut(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    from_unit_id: uuid.UUID
    to_unit_id: uuid.UUID
    from_unit_code: str
    to_unit_code: str
    factor: Decimal
    created_at: datetime


class ConversionCreate(BaseModel):
    from_unit_id: uuid.UUID
    to_unit_id: uuid.UUID
    factor: Decimal = Field(gt=0, max_digits=18, decimal_places=6)

    @model_validator(mode="after")
    def _distinct_units(self) -> "ConversionCreate":
        if self.from_unit_id == self.to_unit_id:
            raise ValueError("from_unit_id and to_unit_id must differ")
        return self


class ProductOut(BaseModel):
    id: uuid.UUID
    sku: str
    barcode: str | None
    name_ar: str
    name: str | None
    description: str | None
    category_id: uuid.UUID | None
    category_name: str | None
    brand_id: uuid.UUID | None
    brand_name: str | None
    base_unit_id: uuid.UUID
    base_unit_code: str
    base_unit_name_ar: str
    purchase_unit_id: uuid.UUID | None
    purchase_unit_code: str | None
    sale_unit_id: uuid.UUID | None
    sale_unit_code: str | None
    # Null unless the caller holds inventory.view_cost.
    cost_price: Decimal | None
    sale_price: Decimal | None
    minimum_stock: Decimal
    tracks_batches: bool
    status: ProductStatus
    stock_quantity: Decimal
    stock_status: StockStatus
    created_at: datetime
    updated_at: datetime


class ProductDetailOut(ProductOut):
    conversions: list[ConversionOut]


class ProductListOut(BaseModel):
    items: list[ProductOut]
    total: int
    page: int
    page_size: int


class ProductCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    barcode: str | None = Field(default=None, max_length=64)
    name_ar: str = Field(min_length=1, max_length=200)
    name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    category_id: uuid.UUID | None = None
    brand_id: uuid.UUID | None = None
    base_unit_id: uuid.UUID
    purchase_unit_id: uuid.UUID | None = None
    sale_unit_id: uuid.UUID | None = None
    cost_price: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    sale_price: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    minimum_stock: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)
    tracks_batches: bool = False

    @field_validator("sku", "name_ar", mode="after")
    @classmethod
    def _clean_required(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned

    @field_validator("barcode", "name", "description", mode="after")
    @classmethod
    def _clean_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ProductUpdate(BaseModel):
    sku: str | None = Field(default=None, min_length=1, max_length=64)
    barcode: str | None = Field(default=None, max_length=64)
    name_ar: str | None = Field(default=None, min_length=1, max_length=200)
    name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    category_id: uuid.UUID | None = None
    brand_id: uuid.UUID | None = None
    base_unit_id: uuid.UUID | None = None
    purchase_unit_id: uuid.UUID | None = None
    sale_unit_id: uuid.UUID | None = None
    cost_price: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    sale_price: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    minimum_stock: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    tracks_batches: bool | None = None

    @field_validator("sku", "name_ar", mode="after")
    @classmethod
    def _clean_required(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned

    @field_validator("barcode", "name", "description", mode="after")
    @classmethod
    def _clean_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None
