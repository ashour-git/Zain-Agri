"""Read-only lookups offered to the assistant model."""

import json
import uuid
from datetime import date, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.assistant.tools import ToolContext, run_tool, tool_schemas
from app.modules.authorization.permissions import Permission, permissions_for
from app.modules.catalog.models import Product
from app.modules.identity.models import MembershipRole
from app.modules.tenancy.context import set_tenant_context
from tests.support import adjust_api, create_product_api, make_batch_row, seeded_login

OWNER = permissions_for(MembershipRole.OWNER)
CASHIER = permissions_for(MembershipRole.CASHIER)


async def _shop(client: AsyncClient, owner_session: AsyncSession) -> tuple[Any, dict[str, str]]:
    _, headers, tenant, _ = await seeded_login(client, owner_session)
    return tenant, headers


async def _product(
    client: AsyncClient,
    headers: dict[str, str],
    name: str,
    quantity: str,
    minimum: str = "10",
    **overrides: Any,
) -> dict[str, Any]:
    product = await create_product_api(
        client,
        headers,
        name_ar=name,
        base_unit="bag",
        minimum_stock=minimum,
        sale_price="950.00",
        cost_price="800.00",
        **overrides,
    )
    if quantity != "0":
        await adjust_api(
            client, headers, product_id=product["id"], quantity=quantity, unit_code="bag"
        )
    return product


async def _ctx(db_session: AsyncSession, tenant_id: Any, permissions: frozenset) -> ToolContext:
    await set_tenant_context(db_session, tenant_id)
    return ToolContext(db=db_session, tenant_id=tenant_id, permissions=permissions)


def _names(schemas: list[dict[str, Any]]) -> list[str]:
    return [schema["function"]["name"] for schema in schemas]


def test_schemas_follow_permissions() -> None:
    assert sorted(_names(tool_schemas(OWNER))) == sorted(
        ["search_products", "low_stock", "recent_movements", "expiring_batches", "product_details"]
    )
    assert _names(tool_schemas(frozenset({Permission.PRODUCTS_READ}))) == ["product_details"]
    assert tool_schemas(frozenset()) == []


async def test_search_returns_quantity_and_hides_cost_for_cashier(
    client: AsyncClient, owner_session: AsyncSession, db_session: AsyncSession
) -> None:
    tenant, headers = await _shop(client, owner_session)
    await _product(client, headers, "سماد يوريا 46%", "12", minimum="20")

    cashier = await run_tool(
        "search_products",
        json.dumps({"query": "يوريا"}),
        await _ctx(db_session, tenant.id, CASHIER),
    )
    row = cashier.result["rows"][0]
    assert row["name"] == "سماد يوريا 46%"
    assert row["quantity"] == "12"
    assert row["minimum"] == "20"
    assert row["status"] == "تحت الحد"
    assert row["unit"] == "شيكارة"
    assert "cost_price" not in row
    assert cashier.label == "بحث: «يوريا»"

    owner = await run_tool(
        "search_products", json.dumps({"query": "يوريا"}), await _ctx(db_session, tenant.id, OWNER)
    )
    assert owner.result["rows"][0]["cost_price"] == "800"


async def test_search_with_no_match_returns_empty_rows(
    client: AsyncClient, owner_session: AsyncSession, db_session: AsyncSession
) -> None:
    tenant, _ = await _shop(client, owner_session)

    outcome = await run_tool(
        "search_products",
        json.dumps({"query": "غير موجود"}),
        await _ctx(db_session, tenant.id, OWNER),
    )

    assert outcome.result == {"rows": []}


async def test_low_stock_lists_out_and_low(
    client: AsyncClient, owner_session: AsyncSession, db_session: AsyncSession
) -> None:
    tenant, headers = await _shop(client, owner_session)
    await _product(client, headers, "مبيد فطري كوبر", "0", minimum="5")
    await _product(client, headers, "بذور طماطم هجين", "4", minimum="10")
    await _product(client, headers, "سماد سوبر فوسفات", "40", minimum="10")

    outcome = await run_tool("low_stock", "{}", await _ctx(db_session, tenant.id, OWNER))

    statuses = {row["name"]: row["status"] for row in outcome.result["rows"]}
    assert statuses == {"مبيد فطري كوبر": "نفد", "بذور طماطم هجين": "تحت الحد"}
    assert outcome.label == "الأصناف تحت الحد"


async def test_other_tenant_rows_never_appear(
    client: AsyncClient, owner_session: AsyncSession, db_session: AsyncSession
) -> None:
    tenant_a, _ = await _shop(client, owner_session)
    _, headers_b = await _shop(client, owner_session)
    await _product(client, headers_b, "سماد يوريا 46%", "30")

    outcome = await run_tool(
        "search_products",
        json.dumps({"query": "يوريا"}),
        await _ctx(db_session, tenant_a.id, OWNER),
    )

    assert outcome.result == {"rows": []}


async def test_recent_movements_uses_arabic_type_and_sign(
    client: AsyncClient, owner_session: AsyncSession, db_session: AsyncSession
) -> None:
    tenant, headers = await _shop(client, owner_session)
    product = await _product(client, headers, "سماد يوريا 46%", "12")
    await adjust_api(
        client,
        headers,
        product_id=product["id"],
        movement_type="adjustment_out",
        quantity="2",
        unit_code="bag",
        reason="كسر شيكارتين",
    )

    outcome = await run_tool(
        "recent_movements", json.dumps({"days": 7}), await _ctx(db_session, tenant.id, OWNER)
    )

    rows = outcome.result["rows"]
    assert [(row["type"], row["quantity"]) for row in rows] == [
        ("تسوية بالنقص", "-2"),
        ("رصيد افتتاحي", "+12"),
    ]
    assert rows[0]["date"] == date.today().isoformat()
    assert outcome.label == "حركات آخر 7 يوم"


async def test_expiring_batches_only_within_window_and_in_stock(
    client: AsyncClient, owner_session: AsyncSession, db_session: AsyncSession
) -> None:
    tenant, headers = await _shop(client, owner_session)
    product = await _product(client, headers, "مبيد فطري كوبر", "0", tracks_batches=True)
    for number, days, quantity in [("SOON", 20, "3"), ("LATER", 200, "5"), ("EMPTY", 10, "0")]:
        response = await client.post(
            "/api/v1/inventory/batches",
            json={
                "product_id": product["id"],
                "batch_number": number,
                "expiry_date": (date.today() + timedelta(days=days)).isoformat(),
            },
            headers=headers,
        )
        assert response.status_code == 201, response.text
        if quantity != "0":
            await adjust_api(
                client,
                headers,
                product_id=product["id"],
                movement_type="adjustment_in",
                quantity=quantity,
                unit_code="bag",
                batch_id=response.json()["id"],
            )

    outcome = await run_tool(
        "expiring_batches", json.dumps({"days": 30}), await _ctx(db_session, tenant.id, OWNER)
    )

    assert [row["batch"] for row in outcome.result["rows"]] == ["SOON"]


async def test_bad_arguments_and_unknown_tool(
    client: AsyncClient, owner_session: AsyncSession, db_session: AsyncSession
) -> None:
    tenant, _ = await _shop(client, owner_session)
    ctx = await _ctx(db_session, tenant.id, OWNER)

    assert (await run_tool("search_products", "{not json", ctx)).result == {
        "error": "bad_arguments"
    }
    assert (await run_tool("recent_movements", '{"days": 500}', ctx)).result == {
        "error": "bad_arguments"
    }
    assert (await run_tool("drop_tables", "{}", ctx)).result == {"error": "not_allowed"}

    no_inventory = await _ctx(db_session, tenant.id, frozenset({Permission.PRODUCTS_READ}))
    assert (await run_tool("low_stock", "{}", no_inventory)).result == {"error": "not_allowed"}


async def test_rows_are_capped_at_20(
    client: AsyncClient, owner_session: AsyncSession, db_session: AsyncSession
) -> None:
    tenant, headers = await _shop(client, owner_session)
    for index in range(23):
        await _product(client, headers, f"بذور رقم {index}", "1", minimum="5")

    outcome = await run_tool("low_stock", "{}", await _ctx(db_session, tenant.id, OWNER))

    assert len(outcome.result["rows"]) == 20


async def test_search_tolerates_article_unit_and_filler_words(
    client: AsyncClient, owner_session: AsyncSession, db_session: AsyncSession
) -> None:
    tenant, headers = await _shop(client, owner_session)
    await _product(client, headers, "سماد يوريا 46%", "12")
    ctx = await _ctx(db_session, tenant.id, OWNER)

    for query in ["اليوريا", "شيكارة اليوريا", "فاضل كام يوريا"]:
        outcome = await run_tool("search_products", json.dumps({"query": query}), ctx)
        assert [row["name"] for row in outcome.result["rows"]] == ["سماد يوريا 46%"], query

    details = await run_tool("product_details", json.dumps({"query": "اليوريا"}), ctx)
    assert details.result["rows"][0]["name"] == "سماد يوريا 46%"


async def test_movements_filter_tolerates_article(
    client: AsyncClient, owner_session: AsyncSession, db_session: AsyncSession
) -> None:
    tenant, headers = await _shop(client, owner_session)
    await _product(client, headers, "سماد يوريا 46%", "12")
    await _product(client, headers, "بذور طماطم هجين", "4")

    outcome = await run_tool(
        "recent_movements",
        json.dumps({"days": 7, "query": "اليوريا"}),
        await _ctx(db_session, tenant.id, OWNER),
    )

    assert [row["product"] for row in outcome.result["rows"]] == ["سماد يوريا 46%"]


def test_query_variants() -> None:
    from app.modules.assistant.tools import query_variants

    assert query_variants("شيكارة اليوريا") == ["شيكارة اليوريا", "يوريا"]
    assert query_variants("بذور الطماطم الهجين") == [
        "بذور الطماطم الهجين",
        "بذور طماطم هجين",
        "طماطم",
        "هجين",
    ]  # capped at MAX_VARIANTS; "بذور" alone would match every seed anyway
    assert query_variants("يوريا") == ["يوريا"]


def test_query_variants_are_capped() -> None:
    from app.modules.assistant.tools import MAX_VARIANTS, query_variants

    long_query = " ".join(f"كلمة{i}" for i in range(30))
    assert len(query_variants(long_query)) == MAX_VARIANTS


async def test_low_stock_reports_total_and_truncation(
    client: AsyncClient, owner_session: AsyncSession, db_session: AsyncSession
) -> None:
    tenant, headers = await _shop(client, owner_session)
    for index in range(23):
        await _product(client, headers, f"صنف {index}", "1", minimum="5")

    outcome = await run_tool("low_stock", "{}", await _ctx(db_session, tenant.id, OWNER))

    assert len(outcome.result["rows"]) == 20
    assert outcome.result["total"] == 23
    assert outcome.result["truncated"] is True


async def test_expiring_batches_ignore_old_empty_batches_beyond_first_page(
    client: AsyncClient, owner_session: AsyncSession, db_session: AsyncSession
) -> None:
    tenant, headers = await _shop(client, owner_session)
    product = await _product(client, headers, "مبيد فطري كوبر", "0", tracks_batches=True)
    product_row = await owner_session.get(Product, uuid.UUID(product["id"]))
    for _ in range(101):
        await make_batch_row(
            owner_session, tenant, product_row, expiry_date=date.today() + timedelta(days=2)
        )
    await owner_session.commit()
    live = await client.post(
        "/api/v1/inventory/batches",
        json={
            "product_id": product["id"],
            "batch_number": "LIVE",
            "expiry_date": (date.today() + timedelta(days=25)).isoformat(),
        },
        headers=headers,
    )
    await adjust_api(
        client,
        headers,
        product_id=product["id"],
        movement_type="adjustment_in",
        quantity="3",
        unit_code="bag",
        batch_id=live.json()["id"],
    )

    outcome = await run_tool(
        "expiring_batches", json.dumps({"days": 30}), await _ctx(db_session, tenant.id, OWNER)
    )

    assert [row["batch"] for row in outcome.result["rows"]] == ["LIVE"]


async def test_product_details_hides_cost_for_cashier(
    client: AsyncClient, owner_session: AsyncSession, db_session: AsyncSession
) -> None:
    tenant, headers = await _shop(client, owner_session)
    await _product(client, headers, "سماد يوريا 46%", "12")

    cashier = await run_tool(
        "product_details",
        json.dumps({"query": "يوريا"}),
        await _ctx(db_session, tenant.id, CASHIER),
    )

    assert cashier.result["rows"][0]["name"] == "سماد يوريا 46%"
    assert "cost_price" not in cashier.result["rows"][0]


async def test_failed_lookup_hides_details_and_keeps_session_usable(
    client: AsyncClient,
    owner_session: AsyncSession,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    from app.modules.inventory import service as inventory_service

    monkeypatch.setattr(logging.getLogger("app.modules.assistant.tools"), "disabled", False)
    tenant, headers = await _shop(client, owner_session)
    await _product(client, headers, "سماد يوريا 46%", "12")
    ctx = await _ctx(db_session, tenant.id, OWNER)

    async def explode(db: AsyncSession, **_: Any) -> Any:
        # A real database error mid-lookup, carrying the user's words as parameters.
        await db.execute(text("SELECT 1/0 WHERE :secret = :secret"), {"secret": "سؤال سري"})

    monkeypatch.setattr(inventory_service, "list_inventory", explode)
    with caplog.at_level("WARNING"):
        failed = await run_tool("low_stock", "{}", ctx)
    monkeypatch.undo()

    assert failed.result == {"error": "lookup_failed"}
    assert "سري" not in caplog.text
    # The session survived: the next lookup works.
    again = await run_tool("search_products", json.dumps({"query": "يوريا"}), ctx)
    assert again.result["rows"][0]["quantity"] == "12"
