import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.modules.customers.models import LedgerKind


def _clean(value: str) -> str:
    return " ".join(value.split())


class CustomerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=30)
    # «رصيد سابق»: what the customer already owed before using the app.
    opening_balance: Decimal | None = Field(default=None, max_digits=14, decimal_places=2)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        cleaned = _clean(value)
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned


class CustomerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=30)
    active: bool | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        return _clean(value) if value is not None else None


class CustomerOut(BaseModel):
    id: uuid.UUID
    name: str
    phone: str | None
    active: bool
    balance: Decimal


class CustomerListOut(BaseModel):
    items: list[CustomerOut]
    total: int
    page: int
    page_size: int


class PaymentIn(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    note: str | None = Field(default=None, max_length=300)


class CorrectionIn(BaseModel):
    amount: Decimal = Field(max_digits=14, decimal_places=2)
    reason: str = Field(min_length=3, max_length=300)

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        cleaned = _clean(value)
        if len(cleaned) < 3:
            raise ValueError("reason is too short")
        return cleaned


class StatementLineOut(BaseModel):
    id: uuid.UUID
    kind: LedgerKind
    amount: Decimal
    balance_after: Decimal
    reference_type: str | None
    reference_id: uuid.UUID | None
    note: str | None
    created_at: datetime
    created_by_name: str | None


class StatementOut(BaseModel):
    customer: CustomerOut
    lines: list[StatementLineOut]
    balance: Decimal
