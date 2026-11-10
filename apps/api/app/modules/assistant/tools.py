"""Read-only lookups the assistant model may call.

Every lookup runs the existing inventory/catalog services on the request's
own database session, so tenant isolation (RLS) and the caller's permissions
apply exactly as they do on the screens. A lookup is offered to the model
only when the caller holds its permission, and is refused again here if the
model asks for it anyway.

Results are shaped for a language model: at most 20 rows, no ids or emails,
numbers as plain strings with Western digits, enum values in Arabic. Cost is
included only for callers allowed to see it.
"""

import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.assistant.quota import SHOP_TZ
from app.modules.authorization.permissions import Permission
from app.modules.catalog import service as catalog
from app.modules.inventory import service as inventory

logger = logging.getLogger(__name__)

MAX_ROWS = 20
# Search attempts per lookup (as typed, cleaned, then single words).
MAX_VARIANTS = 4
# Products a movement search may resolve to ("بذور" can match several).
MAX_PRODUCTS = 5

STOCK_LABELS = {"ok": "متوفر", "low": "تحت الحد", "out": "نفد"}

MOVEMENT_LABELS = {
    "opening_balance": "رصيد افتتاحي",
    "purchase": "توريد مشتريات",
    "sale": "بيع",
    "customer_return": "مرتجع عميل",
    "supplier_return": "مرتجع مورد",
    "adjustment_in": "تسوية بالزيادة",
    "adjustment_out": "تسوية بالنقص",
    "damage": "تالف",
    "expiry": "منتهي الصلاحية",
    "transfer_in": "تحويل وارد",
    "transfer_out": "تحويل صادر",
}


@dataclass(frozen=True)
class ToolContext:
    db: AsyncSession
    tenant_id: uuid.UUID
    permissions: frozenset[Permission]

    @property
    def view_cost(self) -> bool:
        return Permission.INVENTORY_VIEW_COST in self.permissions


@dataclass(frozen=True)
class Found:
    """Rows plus how many matched in total, so the model can say a list is partial."""

    rows: list[dict[str, Any]]
    total: int


@dataclass(frozen=True)
class ToolOutcome:
    name: str
    label: str
    result: dict[str, Any]


# --- argument models -------------------------------------------------------


class _Args(BaseModel):
    # Models sometimes send stray keys (e.g. {"days": 0} to a no-argument tool).
    model_config = ConfigDict(extra="ignore")


class QueryArgs(_Args):
    query: str = Field(min_length=1, max_length=100)


class NoArgs(_Args):
    pass


class MovementArgs(_Args):
    days: int = Field(ge=1, le=90)
    query: str | None = Field(default=None, max_length=100)


class ExpiryArgs(_Args):
    days: int = Field(ge=1, le=365)


# --- Arabic-tolerant search ------------------------------------------------------

# Words people type around a product name that never appear in the name itself.
_NOISE = {
    # units
    "شيكارة",
    "شيكاره",
    "شكارة",
    "شكاره",
    "عبوة",
    "عبوه",
    "زجاجة",
    "زجاجه",
    "كيس",
    "لتر",
    "كيلو",
    "جرام",
    "علبة",
    "علبه",
    "كرتونة",
    "كرتونه",
    "قطعة",
    "قطعه",
    # filler
    "كام",
    "فاضل",
    "باقي",
    "عندنا",
    "عندي",
    "في",
    "من",
    "بتاع",
    "بتاعة",
    "رصيد",
}


def _clean_word(word: str) -> str:
    for prefix in ("لل", "ال"):
        if word.startswith(prefix) and len(word) > len(prefix) + 2:
            return word[len(prefix) :]
    return word


def query_variants(query: str) -> list[str]:
    """The query as typed, then without the article/units/filler, then single words.

    Single words go longest first; on ties the later word first, because the
    category ("بذور", "سماد") usually comes before the specific name.
    """
    words = query.split()
    cleaned = [_clean_word(word) for word in words if word not in _NOISE]
    cleaned = [word for word in cleaned if len(word) >= 2]
    variants = [query.strip(), " ".join(cleaned)]
    if len(cleaned) > 1:
        order = {word: index for index, word in enumerate(cleaned)}
        variants += sorted(cleaned, key=lambda word: (len(word), order[word]), reverse=True)
    unique: list[str] = []
    for variant in variants:
        if variant and variant not in unique:
            unique.append(variant)
    return unique[:MAX_VARIANTS]


# --- formatting --------------------------------------------------------------


def _num(value: Decimal | int | None) -> str | None:
    if value is None:
        return None
    text = format(Decimal(value).normalize(), "f")
    return "0" if text in {"-0", ""} else text


def _status(value: str) -> str:
    return STOCK_LABELS.get(value, value)


def _today() -> Any:
    return datetime.now(SHOP_TZ).date()


# --- lookups -----------------------------------------------------------------


async def _search_products(ctx: ToolContext, args: QueryArgs) -> list[dict[str, Any]]:
    stock = None
    matched = args.query
    for variant in query_variants(args.query):
        stock = await inventory.list_inventory(
            ctx.db, tenant_id=ctx.tenant_id, page=1, page_size=MAX_ROWS, q=variant
        )
        matched = variant
        if stock.items:
            break
    if stock is None:
        return []
    costs: dict[uuid.UUID, Decimal | None] = {}
    if ctx.view_cost and stock.items:
        products = await catalog.list_products(
            ctx.db,
            tenant_id=ctx.tenant_id,
            page=1,
            page_size=MAX_ROWS,
            q=matched,
            view_cost=True,
        )
        costs = {product.id: product.cost_price for product in products.items}

    rows = []
    for item in stock.items:
        row: dict[str, Any] = {
            "name": item.name_ar,
            "sku": item.sku,
            "quantity": _num(item.quantity),
            "unit": item.base_unit_name_ar,
            "minimum": _num(item.minimum_stock),
            "status": _status(item.stock_status),
            "sale_price": _num(item.sale_price),
            "category": item.category_name,
        }
        if ctx.view_cost:
            row["cost_price"] = _num(costs.get(item.product_id))
        rows.append(row)
    return rows


async def _low_stock(ctx: ToolContext, _: NoArgs) -> Found:
    rows: list[dict[str, Any]] = []
    total = 0
    for level in ("out", "low"):
        page = await inventory.list_inventory(
            ctx.db, tenant_id=ctx.tenant_id, page=1, page_size=MAX_ROWS, stock=level
        )
        rows.extend(
            {
                "name": item.name_ar,
                "quantity": _num(item.quantity),
                "unit": item.base_unit_name_ar,
                "minimum": _num(item.minimum_stock),
                "status": _status(item.stock_status),
            }
            for item in page.items
        )
        total += page.total
    return Found(rows, total)


async def _recent_movements(ctx: ToolContext, args: MovementArgs) -> list[dict[str, Any]]:
    since = datetime.now(SHOP_TZ) - timedelta(days=args.days)
    if args.query:
        # Resolve the product first, then ask the database for its movements:
        # filtering a page of recent movements in Python would miss older ones.
        product_ids: list[uuid.UUID] = []
        for variant in query_variants(args.query):
            found = await inventory.list_inventory(
                ctx.db, tenant_id=ctx.tenant_id, page=1, page_size=MAX_PRODUCTS, q=variant
            )
            product_ids = [item.product_id for item in found.items]
            if product_ids:
                break
        movements = []
        for product_id in product_ids:
            page = await inventory.list_movements(
                ctx.db,
                tenant_id=ctx.tenant_id,
                page=1,
                page_size=MAX_ROWS,
                product_id=product_id,
                created_from=since,
            )
            movements.extend(page.items)
        movements.sort(key=lambda movement: movement.created_at, reverse=True)
    else:
        movements = (
            await inventory.list_movements(
                ctx.db, tenant_id=ctx.tenant_id, page=1, page_size=MAX_ROWS, created_from=since
            )
        ).items

    rows = []
    for movement in movements:
        sign = "+" if movement.direction == "in" else "-"
        rows.append(
            {
                "product": movement.product_name_ar,
                "type": MOVEMENT_LABELS.get(
                    str(movement.movement_type), str(movement.movement_type)
                ),
                "quantity": f"{sign}{_num(abs(movement.quantity))}",
                "unit": movement.unit_name_ar,
                "date": movement.created_at.astimezone(SHOP_TZ).date().isoformat(),
                "by": movement.created_by_name,
            }
        )
    return rows


async def _expiring_batches(ctx: ToolContext, args: ExpiryArgs) -> Found:
    page = await inventory.list_batches(
        ctx.db,
        tenant_id=ctx.tenant_id,
        page=1,
        page_size=MAX_ROWS,
        expiring_by=_today() + timedelta(days=args.days),
        in_stock_only=True,
    )
    rows = [
        {
            "product": batch.product_name_ar,
            "batch": batch.batch_number,
            "quantity": _num(batch.quantity),
            "expiry": batch.expiry_date.isoformat() if batch.expiry_date else None,
        }
        for batch in page.items
    ]
    return Found(rows, page.total)


async def _product_details(ctx: ToolContext, args: QueryArgs) -> list[dict[str, Any]]:
    page = None
    for variant in query_variants(args.query):
        page = await catalog.list_products(
            ctx.db,
            tenant_id=ctx.tenant_id,
            page=1,
            page_size=1,
            q=variant,
            view_cost=ctx.view_cost,
        )
        if page.items:
            break
    if page is None or not page.items:
        return []
    product = page.items[0]
    batches = await inventory.list_batches(
        ctx.db, tenant_id=ctx.tenant_id, page=1, page_size=1, product_id=product.id
    )
    row: dict[str, Any] = {
        "name": product.name_ar,
        "sku": product.sku,
        "unit": product.base_unit_name_ar,
        "quantity": _num(product.stock_quantity),
        "minimum": _num(product.minimum_stock),
        "status": _status(product.stock_status),
        "sale_price": _num(product.sale_price),
        "category": product.category_name,
        "tracks_batches": product.tracks_batches,
        "batches": batches.total,
    }
    if ctx.view_cost:
        row["cost_price"] = _num(product.cost_price)
    return [row]


# --- registry ----------------------------------------------------------------


@dataclass(frozen=True)
class _Tool:
    permission: Permission
    args: type[_Args]
    run: Callable[[ToolContext, Any], Awaitable[list[dict[str, Any]] | Found]]
    label: Callable[[Any], str]
    schema: dict[str, Any]


def _fn(
    name: str, description: str, properties: dict[str, Any], required: list[str]
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


_QUERY = {
    "query": {
        "type": "string",
        "description": (
            "Product name only, in Arabic (e.g. يوريا), without units or question words."
        ),
    }
}

TOOLS: dict[str, _Tool] = {
    "search_products": _Tool(
        Permission.INVENTORY_READ,
        QueryArgs,
        _search_products,
        lambda a: f"بحث: «{a.query}»",
        _fn(
            "search_products",
            "Find products by name, code or barcode. Returns current stock, unit, "
            "minimum level, status and sale price.",
            _QUERY,
            ["query"],
        ),
    ),
    "low_stock": _Tool(
        Permission.INVENTORY_READ,
        NoArgs,
        _low_stock,
        lambda _: "الأصناف تحت الحد",
        _fn(
            "low_stock",
            "List products that are out of stock or below their minimum level: what to reorder.",
            {},
            [],
        ),
    ),
    "recent_movements": _Tool(
        Permission.INVENTORY_READ,
        MovementArgs,
        _recent_movements,
        lambda a: f"حركات آخر {a.days} يوم",
        _fn(
            "recent_movements",
            "Stock movements (in and out) during the last N days, newest first. "
            "Optionally only for products whose name contains `query`.",
            {
                "days": {"type": "integer", "minimum": 1, "maximum": 90},
                **_QUERY,
            },
            ["days"],
        ),
    ),
    "expiring_batches": _Tool(
        Permission.INVENTORY_READ,
        ExpiryArgs,
        _expiring_batches,
        lambda a: f"صلاحية خلال {a.days} يوم",
        _fn(
            "expiring_batches",
            "Batches still in stock whose expiry date falls within the next N days.",
            {"days": {"type": "integer", "minimum": 1, "maximum": 365}},
            ["days"],
        ),
    ),
    "product_details": _Tool(
        Permission.PRODUCTS_READ,
        QueryArgs,
        _product_details,
        lambda a: f"تفاصيل: «{a.query}»",
        _fn(
            "product_details",
            "Full card of the best-matching product: unit, minimum, prices, category, "
            "whether it tracks batches and how many.",
            _QUERY,
            ["query"],
        ),
    ),
}


def tool_schemas(permissions: frozenset[Permission]) -> list[dict[str, Any]]:
    return [tool.schema for tool in TOOLS.values() if tool.permission in permissions]


async def run_tool(name: str, raw_arguments: str, ctx: ToolContext) -> ToolOutcome:
    tool = TOOLS.get(name)
    if tool is None or tool.permission not in ctx.permissions:
        return ToolOutcome(name, "", {"error": "not_allowed"})

    try:
        args = tool.args.model_validate(json.loads(raw_arguments or "{}"))
    except (json.JSONDecodeError, ValidationError, TypeError):
        return ToolOutcome(name, "", {"error": "bad_arguments"})

    try:
        # A savepoint: a failed query must not leave the request's transaction
        # aborted for the next lookup, the audit write or the commit.
        async with ctx.db.begin_nested():
            found = await tool.run(ctx, args)
    except Exception as exc:
        # Name only: database errors and tracebacks can carry the user's words.
        logger.warning("assistant_tool_failed", extra={"tool": name, "reason": type(exc).__name__})
        return ToolOutcome(name, tool.label(args), {"error": "lookup_failed"})

    if isinstance(found, Found):
        rows, total = found.rows, max(found.total, len(found.rows))
    else:
        rows, total = found, len(found)
    result: dict[str, Any] = {"rows": rows[:MAX_ROWS]}
    if total > len(result["rows"]):
        # Tell the model the list is partial so it does not present it as complete.
        result["total"] = total
        result["truncated"] = True
    return ToolOutcome(name, tool.label(args), result)
