"""Build one shop's backup workbook (spec 2026-11-12 §3).

The caller sets the tenant context first. Every base query also filters by
``tenant_id``; joined tables are reached only through this shop's own rows.
"""

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from typing import Any
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from openpyxl.cell import Cell, WriteOnlyCell
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Font
from openpyxl.worksheet._write_only import WriteOnlyWorksheet
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.audit.models import AuditLog
from app.modules.backup.labels import (
    AUDIT_ACTION_LABELS_AR,
    ENTITY_LABELS_AR,
    HEADERS,
    MOVEMENT_LABELS_AR,
    NO_AR,
    PRODUCT_STATUS_AR,
    SHEET_ABOUT,
    SHEET_AUDIT,
    SHEET_BALANCES,
    SHEET_BATCHES,
    SHEET_MOVEMENTS,
    SHEET_NAMES,
    SHEET_PRODUCTS,
    SHEET_TAXONOMY,
    TRIMMED_NOTE,
    YES_AR,
)
from app.modules.catalog.models import Brand, Product, ProductCategory, UnitOfMeasure
from app.modules.catalog.service import stock_status
from app.modules.identity.models import Tenant, User
from app.modules.inventory.models import InventoryBalance, ProductBatch, StockMovement

CAIRO = ZoneInfo("Africa/Cairo")
DEFAULT_SIZE_CAP_BYTES = 17 * 1024 * 1024  # under Gmail's 25 MB after base64
TRIM_WINDOW = timedelta(days=365)
_FORMULA_PREFIXES = ("=", "+", "-", "@")
_DATE_FORMAT = "yyyy-mm-dd hh:mm"


@dataclass(frozen=True)
class BuiltWorkbook:
    content: bytes
    filename: str
    row_counts: dict[str, int]
    trimmed: bool


def cairo_date(moment: datetime) -> date:
    return moment.astimezone(CAIRO).date()


def _local(moment: datetime | None) -> datetime | None:
    # Excel has no time zones: show Cairo wall-clock time.
    return moment.astimezone(CAIRO).replace(tzinfo=None) if moment else None


def _name(name_ar: str | None, name: str | None) -> str | None:
    return name_ar or name


class _Writer:
    def __init__(self, book: Workbook) -> None:
        self.book = book
        self.counts: dict[str, int] = {}

    def _cell(self, ws: WriteOnlyWorksheet, value: Any) -> Cell:
        if isinstance(value, str):
            # Control characters (e.g. GS 0x1d in scanned GS1 barcodes) are
            # not allowed in .xlsx and would fail the whole file.
            value = ILLEGAL_CHARACTERS_RE.sub("", value)
        cell = WriteOnlyCell(ws, value=value)
        if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
            cell.data_type = "s"  # shop text, never a formula
        elif isinstance(value, datetime):
            cell.number_format = _DATE_FORMAT
        elif isinstance(value, date):
            cell.number_format = "yyyy-mm-dd"
        return cell

    def sheet(self, title: str, rows: Iterable[Sequence[Any]]) -> None:
        ws: WriteOnlyWorksheet = self.book.create_sheet(title)
        ws.sheet_view.rightToLeft = True
        header = []
        for text in HEADERS[title]:
            cell = WriteOnlyCell(ws, value=text)
            cell.font = Font(bold=True)
            header.append(cell)
        ws.append(header)
        count = 0
        for row in rows:
            ws.append([self._cell(ws, value) for value in row])
            count += 1
        if title != SHEET_ABOUT:
            self.counts[title] = count


async def _products(db: AsyncSession, tenant_id: uuid.UUID) -> list[tuple[Any, ...]]:
    query = (
        select(
            Product,
            func.coalesce(ProductCategory.name_ar, ProductCategory.name),
            func.coalesce(Brand.name_ar, Brand.name),
            UnitOfMeasure.name_ar,
        )
        .outerjoin(
            ProductCategory,
            and_(
                ProductCategory.id == Product.category_id,
                ProductCategory.tenant_id == Product.tenant_id,
            ),
        )
        .outerjoin(Brand, and_(Brand.id == Product.brand_id, Brand.tenant_id == Product.tenant_id))
        .join(UnitOfMeasure, UnitOfMeasure.id == Product.base_unit_id)
        .where(Product.tenant_id == tenant_id)
        .order_by(Product.sku)
    )
    return [
        (
            p.sku,
            p.barcode,
            p.name_ar,
            p.name,
            category,
            brand,
            unit,
            p.cost_price,
            p.sale_price,
            p.minimum_stock,
            YES_AR if p.tracks_batches else NO_AR,
            PRODUCT_STATUS_AR.get(str(p.status), str(p.status)),
        )
        for p, category, brand, unit in (await db.execute(query)).all()
    ]


async def _balances(db: AsyncSession, tenant_id: uuid.UUID) -> list[tuple[Any, ...]]:
    query = (
        select(
            Product.name_ar,
            func.coalesce(InventoryBalance.quantity, Decimal("0")),
            UnitOfMeasure.name_ar,
            Product.minimum_stock,
        )
        .join(UnitOfMeasure, UnitOfMeasure.id == Product.base_unit_id)
        .outerjoin(
            InventoryBalance,
            and_(
                InventoryBalance.product_id == Product.id,
                InventoryBalance.tenant_id == Product.tenant_id,
            ),
        )
        .where(Product.tenant_id == tenant_id)
        .order_by(Product.name_ar)
    )
    rows: list[tuple[Any, ...]] = []
    for name, quantity, unit, minimum in (await db.execute(query)).all():
        below = stock_status(Decimal(quantity), minimum) != "ok"
        rows.append((name, None, Decimal(quantity), unit, YES_AR if below else NO_AR))

    per_batch = (
        select(
            Product.name_ar,
            ProductBatch.batch_number,
            func.sum(StockMovement.base_quantity),
            UnitOfMeasure.name_ar,
        )
        .join(ProductBatch, ProductBatch.id == StockMovement.batch_id)
        .join(Product, Product.id == StockMovement.product_id)
        .join(UnitOfMeasure, UnitOfMeasure.id == Product.base_unit_id)
        .where(StockMovement.tenant_id == tenant_id)
        .group_by(Product.name_ar, ProductBatch.batch_number, UnitOfMeasure.name_ar)
        .order_by(Product.name_ar, ProductBatch.batch_number)
    )
    rows.extend(
        (name, batch, Decimal(quantity), unit, None)
        for name, batch, quantity, unit in (await db.execute(per_batch)).all()
    )
    return rows


async def _movements(
    db: AsyncSession, tenant_id: uuid.UUID, since: datetime | None
) -> list[tuple[Any, ...]]:
    entered_unit = aliased(UnitOfMeasure)
    query = (
        select(
            StockMovement,
            Product.name_ar,
            entered_unit.name_ar,
            ProductBatch.batch_number,
            User.full_name,
        )
        .join(Product, Product.id == StockMovement.product_id)
        .join(entered_unit, entered_unit.id == StockMovement.unit_id)
        .outerjoin(ProductBatch, ProductBatch.id == StockMovement.batch_id)
        .outerjoin(User, User.id == StockMovement.created_by)
        .where(StockMovement.tenant_id == tenant_id)
        .order_by(StockMovement.created_at, StockMovement.id)
    )
    if since is not None:
        query = query.where(StockMovement.created_at >= since)
    return [
        (
            _local(m.created_at),
            product,
            MOVEMENT_LABELS_AR.get(str(m.movement_type), str(m.movement_type)),
            m.quantity,
            unit,
            m.base_quantity,
            m.unit_cost,
            batch,
            m.notes,
            actor,
        )
        for m, product, unit, batch, actor in (await db.execute(query)).all()
    ]


async def _batches(db: AsyncSession, tenant_id: uuid.UUID) -> list[tuple[Any, ...]]:
    query = (
        select(Product.name_ar, ProductBatch.batch_number, ProductBatch.expiry_date)
        .join(Product, Product.id == ProductBatch.product_id)
        .where(ProductBatch.tenant_id == tenant_id)
        .order_by(Product.name_ar, ProductBatch.batch_number)
    )
    return [tuple(row) for row in (await db.execute(query)).all()]


async def _taxonomy(db: AsyncSession, tenant_id: uuid.UUID) -> list[tuple[Any, ...]]:
    parent = aliased(ProductCategory)
    categories = (
        select(
            func.coalesce(ProductCategory.name_ar, ProductCategory.name),
            func.coalesce(parent.name_ar, parent.name),
        )
        .outerjoin(parent, parent.id == ProductCategory.parent_id)
        .where(ProductCategory.tenant_id == tenant_id)
        .order_by(ProductCategory.name)
    )
    brands = (
        select(func.coalesce(Brand.name_ar, Brand.name))
        .where(Brand.tenant_id == tenant_id)
        .order_by(Brand.name)
    )
    rows: list[tuple[Any, ...]] = [
        ("تصنيف", name, parent_name) for name, parent_name in (await db.execute(categories)).all()
    ]
    rows.extend(("علامة تجارية", name, None) for name in (await db.execute(brands)).scalars())
    return rows


def _audit_subject(entry: AuditLog) -> str:
    label = ENTITY_LABELS_AR.get(entry.entity_type, entry.entity_type)
    state = entry.after_state or entry.before_state or {}
    detail = state.get("name_ar") or state.get("name") or state.get("sku")
    return f"{label}: {detail}" if detail else label


async def _audit(
    db: AsyncSession, tenant_id: uuid.UUID, since: datetime | None
) -> list[tuple[Any, ...]]:
    query = (
        select(AuditLog, User.full_name)
        .outerjoin(User, User.id == AuditLog.actor_id)
        .where(AuditLog.tenant_id == tenant_id)
        .order_by(AuditLog.created_at, AuditLog.id)
    )
    if since is not None:
        query = query.where(AuditLog.created_at >= since)
    return [
        (
            _local(entry.created_at),
            actor,
            AUDIT_ACTION_LABELS_AR.get(entry.action, entry.action),
            _audit_subject(entry),
        )
        for entry, actor in (await db.execute(query)).all()
    ]


async def _render(
    db: AsyncSession, tenant: Tenant, now: datetime, since: datetime | None
) -> tuple[bytes, dict[str, int]]:
    book = Workbook(write_only=True)
    writer = _Writer(book)
    writer.sheet(SHEET_PRODUCTS, await _products(db, tenant.id))
    writer.sheet(SHEET_BALANCES, await _balances(db, tenant.id))
    writer.sheet(SHEET_MOVEMENTS, await _movements(db, tenant.id, since))
    writer.sheet(SHEET_BATCHES, await _batches(db, tenant.id))
    writer.sheet(SHEET_TAXONOMY, await _taxonomy(db, tenant.id))
    writer.sheet(SHEET_AUDIT, await _audit(db, tenant.id, since))

    about: list[tuple[Any, ...]] = [
        ("اسم المتجر", tenant.name),
        ("وقت الإنشاء", _local(now)),
        *((f"عدد صفوف «{name}»", writer.counts[name]) for name in SHEET_NAMES[:-1]),
        ("ملاحظة", TRIMMED_NOTE if since is not None else None),
    ]
    writer.sheet(SHEET_ABOUT, about)

    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue(), writer.counts


async def build_workbook(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    now: datetime,
    size_cap_bytes: int = DEFAULT_SIZE_CAP_BYTES,
) -> BuiltWorkbook:
    """One shop's data as an .xlsx. The caller has set the tenant context."""
    tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one()
    content, counts = await _render(db, tenant, now, since=None)
    trimmed = len(content) > size_cap_bytes
    if trimmed:
        content, counts = await _render(db, tenant, now, since=now - TRIM_WINDOW)
    return BuiltWorkbook(
        content=content,
        filename=f"{tenant.slug}-{cairo_date(now).isoformat()}.xlsx",
        row_counts=counts,
        trimmed=trimmed,
    )
