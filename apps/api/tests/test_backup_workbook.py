"""The backup workbook: one shop's data, in Arabic, matching the app screens."""

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from httpx import AsyncClient
from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.backup.labels import (
    AUDIT_ACTION_LABELS_AR,
    HEADERS,
    MOVEMENT_LABELS_AR,
    SHEET_ABOUT,
    SHEET_BALANCES,
    SHEET_MOVEMENTS,
    SHEET_NAMES,
    SHEET_PRODUCTS,
)
from app.modules.backup.workbook import BuiltWorkbook, build_workbook
from app.modules.identity.models import Tenant
from app.modules.inventory.models import StockMovement, StockMovementType
from app.modules.tenancy.context import set_tenant_context
from tests.support import (
    adjust_api,
    create_product_api,
    make_product_row,
    make_tenant,
    seeded_login,
    unit_id,
)

WEB_SRC = Path(__file__).resolve().parents[2] / "web" / "src"
NOW = datetime(2026, 11, 12, 1, 0, tzinfo=UTC)


async def _build(db: AsyncSession, tenant: Tenant, **kwargs: object) -> BuiltWorkbook:
    await set_tenant_context(db, tenant.id)
    return await build_workbook(db, tenant_id=tenant.id, now=kwargs.pop("now", NOW), **kwargs)  # type: ignore[arg-type]


def _sheets(built: BuiltWorkbook) -> dict[str, Worksheet]:
    book = load_workbook(BytesIO(built.content))
    return {ws.title: ws for ws in book.worksheets}


def _rows(ws: Worksheet) -> list[tuple[object, ...]]:
    return [tuple(row) for row in ws.iter_rows(min_row=2, values_only=True)]


def _about(built: BuiltWorkbook) -> dict[object, object]:
    return dict(_rows(_sheets(built)[SHEET_ABOUT]))  # type: ignore[arg-type]


async def test_sheets_in_spec_order_and_rtl(
    db_session: AsyncSession, owner_session: AsyncSession
) -> None:
    tenant = await make_tenant(owner_session)
    await owner_session.commit()

    built = await _build(db_session, tenant)
    book = load_workbook(BytesIO(built.content))

    assert book.sheetnames == list(SHEET_NAMES)
    assert all(ws.sheet_view.rightToLeft for ws in book.worksheets)


async def test_headers_match_spec(db_session: AsyncSession, owner_session: AsyncSession) -> None:
    tenant = await make_tenant(owner_session)
    await owner_session.commit()

    sheets = _sheets(await _build(db_session, tenant))

    for name, headers in HEADERS.items():
        assert tuple(c.value for c in sheets[name][1]) == headers, name
    assert HEADERS[SHEET_PRODUCTS][:3] == ("الرمز", "الباركود", "الاسم")
    assert len(HEADERS[SHEET_PRODUCTS]) == 12


async def test_filename_is_slug_and_cairo_date(
    db_session: AsyncSession, owner_session: AsyncSession
) -> None:
    tenant = await make_tenant(owner_session)
    await owner_session.commit()

    late_utc = datetime(2026, 11, 11, 23, 30, tzinfo=UTC)  # already the 12th in Cairo
    built = await _build(db_session, tenant, now=late_utc)

    assert built.filename == f"{tenant.slug}-2026-11-12.xlsx"


async def test_balances_match_inventory_api(
    client: AsyncClient, db_session: AsyncSession, owner_session: AsyncSession
) -> None:
    _, headers, tenant, _ = await seeded_login(client, owner_session)
    seeds = await create_product_api(client, headers, name_ar="بذور خيار")
    urea = await create_product_api(client, headers, name_ar="يوريا", base_unit="kilogram")
    await adjust_api(client, headers, product_id=seeds["id"], quantity="12")
    await adjust_api(client, headers, product_id=urea["id"], quantity="3", unit_code="kilogram")
    await adjust_api(
        client,
        headers,
        product_id=urea["id"],
        movement_type="adjustment_out",
        quantity="1.5",
        unit_code="kilogram",
        reason="تالف بالمخزن",
    )

    api = (await client.get("/api/v1/inventory", headers=headers)).json()["items"]
    expected = {item["name_ar"]: Decimal(item["quantity"]) for item in api}
    sheet = _rows(_sheets(await _build(db_session, tenant))[SHEET_BALANCES])

    assert {row[0]: Decimal(str(row[2])) for row in sheet} == expected
    assert expected == {"بذور خيار": Decimal("12"), "يوريا": Decimal("1.5")}
    assert {row[0]: row[4] for row in sheet}["يوريا"] == "نعم"  # 1.5 <= minimum 5


async def test_movement_types_are_arabic(
    client: AsyncClient, db_session: AsyncSession, owner_session: AsyncSession
) -> None:
    _, headers, tenant, user = await seeded_login(client, owner_session)
    product = await create_product_api(client, headers)
    await adjust_api(client, headers, product_id=product["id"], quantity="4")

    rows = _rows(_sheets(await _build(db_session, tenant))[SHEET_MOVEMENTS])

    assert len(rows) == 1
    assert rows[0][2] == "رصيد افتتاحي"
    assert rows[0][9] == user.full_name


def _ts_object(path: Path, name: str) -> dict[str, str]:
    source = path.read_text(encoding="utf-8")
    block = source.split(f"{name}:", 1)[1] if f"{name}:" in source else source.split(name, 1)[1]
    block = block.split("};", 1)[0]
    return dict(re.findall(r'"?([\w.]+)"?: "([^"]+)"', block))


def test_labels_match_web() -> None:
    movement = _ts_object(WEB_SRC / "lib" / "catalog.ts", "MOVEMENT_LABELS")
    actions = _ts_object(WEB_SRC / "app" / "(app)" / "audit" / "page.tsx", "ACTION_LABELS")

    assert movement == MOVEMENT_LABELS_AR
    assert actions == AUDIT_ACTION_LABELS_AR


async def test_only_own_shop_rows(db_session: AsyncSession, owner_session: AsyncSession) -> None:
    mine = await make_tenant(owner_session)
    other = await make_tenant(owner_session)
    await make_product_row(owner_session, mine, sku="MINE-1")
    await make_product_row(owner_session, other, sku="OTHER-1")
    await owner_session.commit()

    built = await _build(db_session, mine)
    skus = [row[0] for row in _rows(_sheets(built)[SHEET_PRODUCTS])]

    assert skus == ["MINE-1"]
    assert b"OTHER-1" not in built.content


async def test_empty_shop_builds_valid_workbook(
    db_session: AsyncSession, owner_session: AsyncSession
) -> None:
    tenant = await make_tenant(owner_session)
    await owner_session.commit()

    built = await _build(db_session, tenant)

    assert set(built.row_counts) == set(SHEET_NAMES) - {SHEET_ABOUT}
    assert all(count == 0 for count in built.row_counts.values())
    assert built.trimmed is False
    assert _about(built)["اسم المتجر"] == tenant.name


async def test_formula_like_text_is_not_a_formula(
    db_session: AsyncSession, owner_session: AsyncSession
) -> None:
    tenant = await make_tenant(owner_session)
    await make_product_row(owner_session, tenant, sku="F-1", name_ar="=SUM(A1:A2)")
    await owner_session.commit()

    ws = _sheets(await _build(db_session, tenant))[SHEET_PRODUCTS]
    cell = ws.cell(row=2, column=3)

    assert cell.value == "=SUM(A1:A2)"
    assert cell.data_type == "s"


async def test_size_cap_trims_to_twelve_months(
    db_session: AsyncSession, owner_session: AsyncSession
) -> None:
    tenant = await make_tenant(owner_session)
    product = await make_product_row(owner_session, tenant)
    for age_days, note in ((400, "قديمة"), (10, "حديثة")):
        owner_session.add(
            StockMovement(
                tenant_id=tenant.id,
                product_id=product.id,
                movement_type=StockMovementType.ADJUSTMENT_IN,
                quantity=Decimal("1"),
                unit_id=unit_id("piece"),
                base_quantity=Decimal("1"),
                notes=note,
                created_at=NOW - timedelta(days=age_days),
            )
        )
    await owner_session.commit()

    built = await _build(db_session, tenant, size_cap_bytes=1)
    notes = [row[8] for row in _rows(_sheets(built)[SHEET_MOVEMENTS])]

    assert built.trimmed is True
    assert notes == ["حديثة"]
    assert "آخر 12 شهرًا" in str(_about(built)["ملاحظة"])


async def test_control_characters_are_stripped(
    db_session: AsyncSession, owner_session: AsyncSession
) -> None:
    """Scanners put GS (0x1d) inside GS1 barcodes; Excel files cannot hold it."""
    tenant = await make_tenant(owner_session)
    product = await make_product_row(owner_session, tenant, sku="GS1-1")
    product.barcode = "010628517260101"
    await owner_session.commit()

    ws = _sheets(await _build(db_session, tenant))[SHEET_PRODUCTS]

    assert ws.cell(row=2, column=2).value == "010628517260101"
