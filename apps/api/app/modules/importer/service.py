"""Smart import: analyze a sheet, preview the effect, create products and stock.

The flow is stateless. The browser keeps the parsed rows and sends them back
with the mapping; preview and commit both run ``build_plan``, so what the owner
confirmed is checked again against the database at the moment of writing.
"""

import asyncio
import io
import logging
import re
import uuid
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, UnprocessableError
from app.modules.assistant.llm import LLM
from app.modules.audit import service as audit
from app.modules.auth.dependencies import TenantContext
from app.modules.authorization.permissions import Permission
from app.modules.catalog.models import Brand, Product, ProductCategory, UnitOfMeasure
from app.modules.catalog.schemas import ProductCreate
from app.modules.catalog.service import create_product_core
from app.modules.importer.mapping import FIELDS, Column, propose_mapping
from app.modules.importer.normalize import is_total_row, normalize_name, parse_number, resolve_unit
from app.modules.importer.parser import TOO_MANY_ROWS, find_header_row, read_sheet
from app.modules.importer.schemas import (
    AnalyzeOut,
    ColumnOut,
    CommitOut,
    ImportRequest,
    PreviewCounts,
    PreviewOut,
    PreviewRow,
)
from app.modules.inventory.models import StockMovementType
from app.modules.inventory.service import apply_movement

logger = logging.getLogger("zain.importer")

# Each product costs about ten queries (product, audit, opening balance...).
# The limit keeps one request well inside the function time limit.
MAX_ROWS = 500
SAMPLES_PER_COLUMN = 3
OPENING_REASON = "استيراد من Excel"

NAME_REQUIRED = "Map a column to the product name"
FIELD_TWICE = "Each field can be used for one column only"
UNKNOWN_FIELD = "Unknown import field"
HAS_PROBLEMS = "The sheet has rows with problems"
CHANGED = "The data changed during the import"
EMPTY_UPLOAD = "The upload is empty"

_LABELS = {
    "sale_price": "السعر",
    "cost_price": "التكلفة",
    "minimum_stock": "الحد الأدنى",
    "quantity": "الكمية",
}
_SKU_PATTERN = re.compile(r"^z-(\d+)$", re.IGNORECASE)
_MAX_VALUE = Decimal("1000000000000")


class _RowError(Exception):
    pass


@dataclass
class PlannedRow:
    row_number: int
    status: str
    reason: str | None = None
    warnings: list[str] = field(default_factory=list)
    name: str | None = None
    sku: str | None = None
    barcode: str | None = None
    unit_id: uuid.UUID | None = None
    unit_name: str | None = None
    category_key: str | None = None
    brand_key: str | None = None
    cost: Decimal | None = None
    sale: Decimal | None = None
    minimum: Decimal = Decimal("0")
    quantity: Decimal | None = None


@dataclass
class Plan:
    rows: list[PlannedRow]
    ignored_blank: int
    new_categories: dict[str, str]
    new_brands: dict[str, str]
    category_ids: dict[str, uuid.UUID]
    brand_ids: dict[str, uuid.UUID]
    notices: list[str]


# --- analyze -------------------------------------------------------------------------


async def analyze(content: bytes, filename: str, sheet: str | None, llm: LLM | None) -> AnalyzeOut:
    data = await asyncio.to_thread(read_sheet, content, filename, sheet)
    header_index = find_header_row(data.rows)
    data_rows = data.rows[header_index + 1 :]
    if len(data_rows) > MAX_ROWS:
        raise UnprocessableError(TOO_MANY_ROWS)

    columns = [
        Column(
            index=index,
            header=header or f"عمود {index + 1}",
            samples=[
                value for value in (row[index] for row in data_rows if index < len(row)) if value
            ][:SAMPLES_PER_COLUMN],
        )
        for index, header in enumerate(data.rows[header_index])
    ]
    mapping, assistant_used = await propose_mapping(columns, llm)
    return AnalyzeOut(
        sheet_names=data.sheet_names,
        sheet=data.sheet,
        header_row=header_index + 1,
        first_data_row=header_index + 2,
        columns=[
            ColumnOut(
                index=column.index,
                header=column.header,
                samples=column.samples,
                field=mapping[column.index][0] if column.index in mapping else None,
                source=mapping[column.index][1] if column.index in mapping else None,
            )
            for column in columns
        ],
        rows=data_rows,
        assistant_available=llm is not None,
        assistant_used=assistant_used,
    )


# --- planning ------------------------------------------------------------------------


def _validate_mapping(mapping: dict[int, str]) -> dict[str, int]:
    fields = list(mapping.values())
    if any(f not in FIELDS for f in fields):
        raise UnprocessableError(UNKNOWN_FIELD)
    if len(set(fields)) != len(fields):
        raise UnprocessableError(FIELD_TWICE)
    if "name_ar" not in fields:
        raise UnprocessableError(NAME_REQUIRED)
    return {f: index for index, f in mapping.items()}


def _number(raw: str, field_name: str, *, places: str) -> Decimal | None:
    label = _LABELS[field_name]
    try:
        value = parse_number(raw)
    except ValueError as exc:
        raise _RowError(f"«{raw}» ليست رقمًا في خانة {label}") from exc
    if value is None:
        return None
    if value < 0:
        raise _RowError(f"قيمة سالبة في خانة {label}")
    if value >= _MAX_VALUE:
        raise _RowError(f"قيمة كبيرة جدًا في خانة {label}")
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


async def build_plan(db: AsyncSession, context: TenantContext, payload: ImportRequest) -> Plan:
    index_of = _validate_mapping(payload.mapping)
    if len(payload.rows) > MAX_ROWS:
        raise UnprocessableError(TOO_MANY_ROWS)
    tenant_id = context.tenant.id
    can_see_cost = context.allows(Permission.INVENTORY_VIEW_COST)

    units = list((await db.execute(select(UnitOfMeasure))).scalars())
    unit_by_code = {unit.code: unit for unit in units}
    default_unit = next((u for u in units if u.id == payload.default_unit_id), None)
    if payload.default_unit_id is not None and default_unit is None:
        raise UnprocessableError("Unknown unit of measure")
    default_unit = default_unit or unit_by_code["piece"]

    existing = (
        await db.execute(
            select(Product.sku, Product.barcode, Product.name_ar, Product.base_unit_id).where(
                Product.tenant_id == tenant_id
            )
        )
    ).all()
    taken_skus = {sku.lower() for sku, _, _, _ in existing}
    taken_barcodes = {barcode for _, barcode, _, _ in existing if barcode}
    taken_names = {(normalize_name(name), unit_id) for _, _, name, unit_id in existing}

    category_ids: dict[str, uuid.UUID] = {}
    for category in (
        await db.execute(select(ProductCategory).where(ProductCategory.tenant_id == tenant_id))
    ).scalars():
        for label in (category.name_ar, category.name):
            if label:
                category_ids.setdefault(normalize_name(label), category.id)
    brand_ids: dict[str, uuid.UUID] = {}
    for brand in (await db.execute(select(Brand).where(Brand.tenant_id == tenant_id))).scalars():
        for label in (brand.name_ar, brand.name):
            if label:
                brand_ids.setdefault(normalize_name(label), brand.id)

    def cell(row: list[str], name: str) -> str:
        index = index_of.get(name)
        return row[index].strip() if index is not None and index < len(row) else ""

    seen_skus: dict[str, int] = {}
    seen_barcodes: dict[str, int] = {}
    seen_names: dict[tuple[str, uuid.UUID], int] = {}
    new_categories: dict[str, str] = {}
    new_brands: dict[str, str] = {}
    notices: list[str] = []
    rows: list[PlannedRow] = []
    ignored_blank = 0

    for offset, raw in enumerate(payload.rows):
        number = payload.first_row_number + offset
        if not any(value.strip() for value in raw):
            ignored_blank += 1
            continue
        name = cell(raw, "name_ar")
        planned = PlannedRow(row_number=number, status="create", name=name or None)
        rows.append(planned)

        if name and is_total_row(name):
            planned.status, planned.reason = "skip", "صف إجمالي، لا يُستورد"
            continue
        try:
            if not name:
                raise _RowError("اسم الصنف فارغ")
            if len(name) > 200:
                raise _RowError("اسم الصنف أطول من 200 حرف")
            planned.sale = _number(cell(raw, "sale_price"), "sale_price", places="0.01")
            planned.minimum = _number(
                cell(raw, "minimum_stock"), "minimum_stock", places="0.0001"
            ) or Decimal("0")
            planned.quantity = _number(cell(raw, "quantity"), "quantity", places="0.0001")
            cost = _number(cell(raw, "cost_price"), "cost_price", places="0.01")
            if cost is not None and not can_see_cost:
                notice = "تجاهلنا عمود التكلفة لأن صلاحياتك لا تسمح بتسجيل التكلفة"
                if notice not in notices:
                    notices.append(notice)
                cost = None
            planned.cost = cost
            sku, barcode = cell(raw, "sku"), cell(raw, "barcode")
            if len(sku) > 64 or len(barcode) > 64:
                raise _RowError("الرمز أو الباركود أطول من 64 حرفًا")
            planned.sku, planned.barcode = sku or None, barcode or None
        except _RowError as exc:
            planned.status, planned.reason = "error", str(exc)
            continue

        unit_text = cell(raw, "unit")
        unit = default_unit
        if unit_text:
            code = resolve_unit(unit_text)
            if code is not None and code in unit_by_code:
                unit = unit_by_code[code]
            else:
                planned.warnings.append(
                    f"الوحدة «{unit_text}» غير معروفة، استُخدمت «{default_unit.name_ar}»"
                )
        planned.unit_id, planned.unit_name = unit.id, unit.name_ar

        name_key = (normalize_name(name), unit.id)
        if planned.sku and planned.sku.lower() in taken_skus:
            planned.status, planned.reason = "skip", f"رمز المنتج «{planned.sku}» موجود بالفعل"
        elif planned.sku and planned.sku.lower() in seen_skus:
            first = seen_skus[planned.sku.lower()]
            planned.status, planned.reason = "skip", f"مكرر في الملف (الصف {first})"
        elif planned.barcode and planned.barcode in taken_barcodes:
            planned.status, planned.reason = "skip", "الباركود موجود بالفعل لمنتج آخر"
        elif planned.barcode and planned.barcode in seen_barcodes:
            first = seen_barcodes[planned.barcode]
            planned.status, planned.reason = "skip", f"مكرر في الملف (الصف {first})"
        elif name_key in taken_names:
            planned.status, planned.reason = "skip", "منتج بنفس الاسم والوحدة موجود بالفعل"
        elif name_key in seen_names:
            first = seen_names[name_key]
            planned.status, planned.reason = "skip", f"مكرر في الملف (الصف {first})"
        if planned.status != "create":
            continue

        if planned.sku:
            seen_skus[planned.sku.lower()] = number
        if planned.barcode:
            seen_barcodes[planned.barcode] = number
        seen_names[name_key] = number

        for field_name, known, pending, allow in (
            ("category", category_ids, new_categories, payload.create_categories),
            ("brand", brand_ids, new_brands, payload.create_brands),
        ):
            text = cell(raw, field_name)
            if not text:
                continue
            key = normalize_name(text)
            if key in known:
                pass
            elif allow:
                pending.setdefault(key, text)
            else:
                label = "التصنيف" if field_name == "category" else "الشركة"
                planned.warnings.append(f"{label} «{text}» غير موجود، تُرك فارغًا")
                continue
            if field_name == "category":
                planned.category_key = key
            else:
                planned.brand_key = key

    # Codes for rows that came without one: Z-00001, Z-00002... never reused.
    highest = max((int(m.group(1)) for s in taken_skus if (m := _SKU_PATTERN.match(s))), default=0)
    used = taken_skus | set(seen_skus)
    for planned in rows:
        if planned.status != "create" or planned.sku:
            continue
        while True:
            highest += 1
            candidate = f"Z-{highest:05d}"
            if candidate.lower() not in used:
                break
        planned.sku = candidate
        used.add(candidate.lower())

    return Plan(
        rows=rows,
        ignored_blank=ignored_blank,
        new_categories=new_categories,
        new_brands=new_brands,
        category_ids=category_ids,
        brand_ids=brand_ids,
        notices=notices,
    )


# --- preview and commit --------------------------------------------------------------


def _counts(plan: Plan) -> PreviewCounts:
    return PreviewCounts(
        create=sum(1 for r in plan.rows if r.status == "create"),
        skip=sum(1 for r in plan.rows if r.status == "skip"),
        error=sum(1 for r in plan.rows if r.status == "error"),
    )


async def preview(db: AsyncSession, context: TenantContext, payload: ImportRequest) -> PreviewOut:
    plan = await build_plan(db, context, payload)
    creating = [r for r in plan.rows if r.status == "create"]
    used_categories = {r.category_key for r in creating}
    used_brands = {r.brand_key for r in creating}
    return PreviewOut(
        counts=_counts(plan),
        ignored_blank=plan.ignored_blank,
        rows=[
            PreviewRow(
                row_number=r.row_number,
                status=r.status,
                reason_ar=r.reason,
                warnings=r.warnings,
                name_ar=r.name,
                sku=r.sku if r.status == "create" else None,
                unit_name_ar=r.unit_name,
                quantity=r.quantity,
                sale_price=r.sale,
            )
            for r in plan.rows
        ],
        new_categories=[n for k, n in plan.new_categories.items() if k in used_categories],
        new_brands=[n for k, n in plan.new_brands.items() if k in used_brands],
        notices=plan.notices,
    )


async def commit(
    db: AsyncSession, context: TenantContext, actor_id: uuid.UUID, payload: ImportRequest
) -> CommitOut:
    plan = await build_plan(db, context, payload)
    counts = _counts(plan)
    if counts.error and not payload.skip_errors:
        raise ConflictError(HAS_PROBLEMS)
    creating = [r for r in plan.rows if r.status == "create"]
    skipped = counts.skip + counts.error
    if not creating:
        return CommitOut(
            created=0, skipped=skipped, opening_balances=0, new_categories=0, new_brands=0
        )

    tenant_id = context.tenant.id
    category_ids = dict(plan.category_ids)
    brand_ids = dict(plan.brand_ids)
    made_categories = made_brands = openings = 0
    try:
        for key in sorted({r.category_key for r in creating if r.category_key} - set(category_ids)):
            name = plan.new_categories[key]
            category = ProductCategory(tenant_id=tenant_id, name=name, name_ar=name)
            db.add(category)
            await db.flush()
            category_ids[key] = category.id
            made_categories += 1
        for key in sorted({r.brand_key for r in creating if r.brand_key} - set(brand_ids)):
            name = plan.new_brands[key]
            brand = Brand(tenant_id=tenant_id, name=name, name_ar=name)
            db.add(brand)
            await db.flush()
            brand_ids[key] = brand.id
            made_brands += 1

        for row in creating:
            assert row.unit_id is not None and row.sku is not None and row.name is not None
            product = await create_product_core(
                db,
                context=context,
                actor_id=actor_id,
                payload=ProductCreate(
                    sku=row.sku,
                    barcode=row.barcode,
                    name_ar=row.name,
                    category_id=category_ids.get(row.category_key) if row.category_key else None,
                    brand_id=brand_ids.get(row.brand_key) if row.brand_key else None,
                    base_unit_id=row.unit_id,
                    cost_price=row.cost,
                    sale_price=row.sale,
                    minimum_stock=row.minimum,
                ),
                validated=True,
            )
            if row.quantity is not None and row.quantity > 0:
                await apply_movement(
                    db,
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                    product_id=product.id,
                    movement_type=StockMovementType.OPENING_BALANCE,
                    quantity=row.quantity,
                    unit_id=row.unit_id,
                    reason=OPENING_REASON,
                )
                openings += 1

        await audit.record(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="import.committed",
            entity_type="import",
            meta={
                "created": len(creating),
                "skipped": skipped,
                "opening_balances": openings,
                "new_categories": made_categories,
                "new_brands": made_brands,
            },
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError(CHANGED) from exc

    logger.info(
        "import.committed",
        extra={"tenant_id": str(tenant_id), "rows": len(creating), "result": "created"},
    )
    return CommitOut(
        created=len(creating),
        skipped=skipped,
        opening_balances=openings,
        new_categories=made_categories,
        new_brands=made_brands,
    )


# --- template ------------------------------------------------------------------------

TEMPLATE_HEADERS = (
    "اسم الصنف",
    "كود الصنف",
    "الوحدة",
    "سعر البيع",
    "سعر الشراء",
    "الحد الأدنى",
    "الكمية الحالية",
    "الباركود",
    "التصنيف",
    "الشركة",
)
_TEMPLATE_EXAMPLE: tuple[Any, ...] = (
    "يوريا 46%",
    "UREA-46",
    "كيلو",
    450,
    380,
    5,
    40,
    "",
    "أسمدة",
    "الشركة العربية",
)
_TEMPLATE_NOTES = (
    "اكتب كل منتج في صف، وابدأ من الصف الثاني بعد العناوين.",
    "الخانة الوحيدة المطلوبة هي «اسم الصنف». الباقي اختياري.",
    "«كود الصنف»: إذا تُرك فارغًا نعطيه رمزًا تلقائيًا مثل Z-00001.",
    "«الوحدة»: كيلو، جرام، لتر، مل، شيكارة، زجاجة، كرتونة، عبوة، قطعة.",
    "«الكمية الحالية» تُسجَّل كرصيد افتتاحي.",
    "احذف صف المثال قبل الاستيراد.",
)


def build_template() -> bytes:
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.title = "المنتجات"
    sheet.sheet_view.rightToLeft = True
    sheet.append(list(TEMPLATE_HEADERS))
    sheet.append(list(_TEMPLATE_EXAMPLE))
    notes = book.create_sheet("تعليمات")
    notes.sheet_view.rightToLeft = True
    for line in _TEMPLATE_NOTES:
        notes.append([line])
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()
