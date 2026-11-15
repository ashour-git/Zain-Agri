import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

MONEY = {"max_digits": 14, "decimal_places": 2}


class SaleLineIn(BaseModel):
    product_id: uuid.UUID
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=4)
    # The unit the shelf/customer counted in; the product's base unit when omitted.
    unit_id: uuid.UUID | None = None
    # Price per unit_id. Omitted means the product's sale price; a different
    # value needs sales.discount.
    unit_price: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)


class SaleIn(BaseModel):
    customer_id: uuid.UUID | None = None
    lines: list[SaleLineIn] = Field(min_length=1, max_length=200)
    discount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    # Omitted means paid in full.
    paid: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    # Created once per sale screen by the client; a retry reuses it.
    idempotency_key: str = Field(min_length=16, max_length=80)


class BatchDrawOut(BaseModel):
    batch_id: uuid.UUID
    batch_number: str
    base_quantity: Decimal


class SaleLineOut(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    name_ar: str
    unit_id: uuid.UUID
    unit_name_ar: str
    quantity: Decimal
    base_quantity: Decimal
    unit_price: Decimal
    line_total: Decimal
    returned_quantity: Decimal
    batches: list[BatchDrawOut]


class CustomerRef(BaseModel):
    id: uuid.UUID
    name: str
    phone: str | None


class SaleOut(BaseModel):
    id: uuid.UUID
    number: int
    customer: CustomerRef | None
    lines: list[SaleLineOut]
    subtotal: Decimal
    discount: Decimal
    total: Decimal
    paid: Decimal
    credit: Decimal
    returned_total: Decimal
    created_at: datetime
    created_by_name: str | None
    shared: bool


class SaleSummaryOut(BaseModel):
    id: uuid.UUID
    number: int
    customer_name: str | None
    total: Decimal
    credit: Decimal
    created_at: datetime
    created_by_name: str | None


class SaleListOut(BaseModel):
    items: list[SaleSummaryOut]
    total: int
    page: int
    page_size: int


class ReturnLineIn(BaseModel):
    line_id: uuid.UUID
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=4)


class ReturnIn(BaseModel):
    lines: list[ReturnLineIn] = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=3, max_length=300)

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if len(cleaned) < 3:
            raise ValueError("reason is too short")
        return cleaned


class ReturnOut(BaseModel):
    id: uuid.UUID
    number: int
    total: Decimal
    credit_reduction: Decimal
    cash_refund: Decimal


class ShareOut(BaseModel):
    url: str


class PublicLineOut(BaseModel):
    name_ar: str
    unit_name_ar: str
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal


class PublicInvoiceOut(BaseModel):
    """What a customer sees from a link: no phone, no account balance."""

    shop_name: str
    number: int
    created_at: datetime
    lines: list[PublicLineOut]
    subtotal: Decimal
    discount: Decimal
    total: Decimal
    paid: Decimal
    remaining: Decimal
    returned_total: Decimal
