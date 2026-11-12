"""The import API: analyze, preview, commit and the blank template."""

from collections.abc import Iterator
from decimal import Decimal
from io import BytesIO
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from openpyxl import Workbook
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.assistant.quota import QuotaExceeded, assistant_quota
from app.modules.assistant.router import get_llm
from app.modules.identity.models import MembershipRole
from app.modules.importer import service as importer_service
from app.modules.importer.parser import read_sheet
from tests.support import create_product_api, seeded_login
from tests.test_importer_mapping import FakeLLM

BASE = "/api/v1/imports"


def _xlsx(rows: list[list[object]]) -> bytes:
    book = Workbook()
    sheet = book.active
    for row in rows:
        sheet.append(row)
    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()


STANDARD_HEADERS = ["اسم الصنف", "الوحدة", "سعر البيع", "الحد الأدنى", "الكمية الحالية"]
STANDARD_MAPPING = {0: "name_ar", 1: "unit", 2: "sale_price", 3: "minimum_stock", 4: "quantity"}


async def _analyze(
    client: AsyncClient, headers: dict[str, str], content: bytes, filename: str = "جرد.xlsx"
) -> Any:
    return await client.post(
        f"{BASE}/analyze",
        params={"filename": filename},
        content=content,
        headers={**headers, "Content-Type": "application/octet-stream"},
    )


def _body(
    rows: list[list[str]], mapping: dict[int, str] | None = None, **extra: Any
) -> dict[str, Any]:
    return {
        "mapping": {str(k): v for k, v in (mapping or STANDARD_MAPPING).items()},
        "rows": rows,
        "first_row_number": 2,
        **extra,
    }


async def _preview(client: AsyncClient, headers: dict[str, str], body: dict[str, Any]) -> Any:
    return await client.post(f"{BASE}/preview", json=body, headers=headers)


async def _commit(client: AsyncClient, headers: dict[str, str], body: dict[str, Any]) -> Any:
    return await client.post(f"{BASE}/commit", json=body, headers=headers)


async def _inventory(client: AsyncClient, headers: dict[str, str]) -> dict[str, Decimal]:
    items = (await client.get("/api/v1/inventory?page_size=100", headers=headers)).json()["items"]
    return {item["name_ar"]: Decimal(item["quantity"]) for item in items}


@pytest.fixture
def llm(test_app: FastAPI) -> Iterator[list[FakeLLM]]:
    holder: list[FakeLLM] = []
    test_app.dependency_overrides[get_llm] = lambda: holder[0] if holder else None
    yield holder
    test_app.dependency_overrides.pop(get_llm, None)


# --- analyze -----------------------------------------------------------------------


async def test_analyze_maps_the_columns_and_returns_the_rows(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    content = _xlsx(
        [
            ["جرد مؤسسة زين"],
            [],
            STANDARD_HEADERS,
            ["يوريا 46%", "شيكارة", 450, 5, 40],
            ["بذور خيار", "قطعة", 30, 10, 25],
        ]
    )

    response = await _analyze(client, headers, content)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["header_row"] == 3
    assert body["first_data_row"] == 4
    assert [c["field"] for c in body["columns"]] == [
        "name_ar",
        "unit",
        "sale_price",
        "minimum_stock",
        "quantity",
    ]
    assert {c["source"] for c in body["columns"]} == {"rules"}
    assert body["columns"][0]["samples"] == ["يوريا 46%", "بذور خيار"]
    assert body["rows"] == [
        ["يوريا 46%", "شيكارة", "450", "5", "40"],
        ["بذور خيار", "قطعة", "30", "10", "25"],
    ]
    assert body["assistant_used"] is False


async def test_the_assistant_fills_unknown_headers_and_uses_one_question(
    client: AsyncClient, owner_session: AsyncSession, llm: list[FakeLLM]
) -> None:
    llm.append(FakeLLM('{"columns": [{"index": 1, "field": "quantity"}]}'))
    _, headers, tenant, _ = await seeded_login(client, owner_session)
    before = assistant_quota.remaining(tenant.id, 100)
    content = _xlsx([["الصنف", "المتوفر حاليا"], ["يوريا", 12]])

    response = await _analyze(client, headers, content)

    columns = response.json()["columns"]
    assert [(c["field"], c["source"]) for c in columns] == [
        ("name_ar", "rules"),
        ("quantity", "ai"),
    ]
    assert response.json()["assistant_used"] is True
    assert assistant_quota.remaining(tenant.id, 100) == before - 1


async def test_no_question_is_spent_when_the_rules_cover_everything(
    client: AsyncClient, owner_session: AsyncSession, llm: list[FakeLLM]
) -> None:
    llm.append(FakeLLM('{"columns": []}'))
    _, headers, tenant, _ = await seeded_login(client, owner_session)
    before = assistant_quota.remaining(tenant.id, 100)

    await _analyze(client, headers, _xlsx([["الصنف", "الكمية"], ["يوريا", 1]]))

    assert llm[0].calls == []
    assert assistant_quota.remaining(tenant.id, 100) == before


async def test_a_used_up_daily_limit_still_gives_the_rule_mapping(
    client: AsyncClient,
    owner_session: AsyncSession,
    llm: list[FakeLLM],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm.append(FakeLLM('{"columns": [{"index": 1, "field": "quantity"}]}'))

    def exhausted(*_: Any, **__: Any) -> int:
        raise QuotaExceeded(60)

    monkeypatch.setattr(assistant_quota, "consume", exhausted)
    _, headers, _, _ = await seeded_login(client, owner_session)

    response = await _analyze(client, headers, _xlsx([["الصنف", "المتوفر حاليا"], ["يوريا", 12]]))

    assert response.status_code == 200
    assert [c["field"] for c in response.json()["columns"]] == ["name_ar", None]
    assert llm[0].calls == []


async def test_a_failing_assistant_gives_the_question_back(
    client: AsyncClient, owner_session: AsyncSession, llm: list[FakeLLM]
) -> None:
    from app.modules.assistant.llm import AssistantUnavailable

    llm.append(FakeLLM(AssistantUnavailable()))
    _, headers, tenant, _ = await seeded_login(client, owner_session)
    before = assistant_quota.remaining(tenant.id, 100)

    response = await _analyze(client, headers, _xlsx([["الصنف", "المتوفر حاليا"], ["يوريا", 12]]))

    assert response.status_code == 200
    assert assistant_quota.remaining(tenant.id, 100) == before


@pytest.mark.parametrize(
    ("filename", "content", "message"),
    [
        ("old.xls", b"x", "ملفات xls القديمة غير مدعومة. افتح الملف في Excel واحفظه بصيغة xlsx."),
        ("notes.pdf", b"x", "الملف غير مدعوم. استخدم ملف Excel بصيغة xlsx أو ملف csv."),
        ("fake.xlsx", b"not a zip", "تعذّرت قراءة الملف. تأكد أنه ملف Excel أو csv سليم."),
    ],
)
async def test_bad_files_get_an_arabic_explanation(
    client: AsyncClient, owner_session: AsyncSession, filename: str, content: bytes, message: str
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)

    response = await _analyze(client, headers, content, filename)

    assert response.status_code == 422
    assert response.json()["error"]["message"] == message


async def test_an_empty_upload_is_refused(client: AsyncClient, owner_session: AsyncSession) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)

    response = await _analyze(client, headers, b"")

    assert response.status_code == 422


async def test_a_sheet_with_too_many_rows_is_refused(
    client: AsyncClient, owner_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(importer_service, "MAX_ROWS", 3)
    _, headers, _, _ = await seeded_login(client, owner_session)
    content = _xlsx([["الصنف"]] + [[f"صنف {i}"] for i in range(4)])

    response = await _analyze(client, headers, content)

    assert response.status_code == 422
    assert "عدد الصفوف" in response.json()["error"]["message"]


# --- preview -----------------------------------------------------------------------


async def test_preview_reports_create_skip_and_error_rows(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    await create_product_api(client, headers, sku="OLD-1", name_ar="يوريا 46%")
    rows = [
        ["يوريا 46%", "قطعة", "450", "5", "40"],  # exists already
        ["بذور خيار", "قطعة", "30", "10", "25"],  # new
        ["بذور خيار", "قطعة", "30", "10", "5"],  # repeated in the file
        ["مبيد", "لتر", "abc", "", ""],  # price is not a number
        ["الإجمالي", "", "", "", "70"],  # totals row
        ["", "", "", "", ""],  # blank
        ["", "قطعة", "5", "", ""],  # no name
    ]

    response = await _preview(client, headers, _body(rows))

    assert response.status_code == 200, response.text
    body = response.json()
    statuses = [(r["row_number"], r["status"]) for r in body["rows"]]
    assert statuses == [
        (2, "skip"),
        (3, "create"),
        (4, "skip"),
        (5, "error"),
        (6, "skip"),
        (8, "error"),
    ]
    assert (body["counts"]["create"], body["counts"]["skip"], body["counts"]["error"]) == (1, 3, 2)
    assert body["ignored_blank"] == 1
    reasons = {r["row_number"]: r["reason_ar"] for r in body["rows"]}
    assert "موجود بالفعل" in reasons[2]
    assert "مكرر في الملف" in reasons[4]
    assert "السعر" in reasons[5]
    assert "إجمالي" in reasons[6]
    assert "اسم" in reasons[8]


async def test_numbers_in_arabic_digits_and_with_currency_text(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    rows = [["سماد", "قطعة", "١٬٢٥٠٫٥٠ ج.م", "٥", "٤٠"]]

    body = (await _preview(client, headers, _body(rows))).json()

    [row] = body["rows"]
    assert row["status"] == "create"
    assert Decimal(row["sale_price"]) == Decimal("1250.50")
    assert Decimal(row["quantity"]) == Decimal("40")


async def test_an_unknown_unit_uses_the_default_and_warns(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)

    body = (await _preview(client, headers, _body([["سماد", "قنطار", "10", "", "3"]]))).json()

    [row] = body["rows"]
    assert row["status"] == "create"
    assert row["unit_name_ar"] == "قطعة"
    assert any("قنطار" in warning for warning in row["warnings"])


async def test_the_name_column_is_required(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)

    response = await _preview(client, headers, _body([["10"]], {0: "sale_price"}))

    assert response.status_code == 422
    assert response.json()["error"]["message"] == "اختر العمود الذي يحتوي على اسم الصنف."


async def test_one_field_cannot_be_used_for_two_columns(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)

    response = await _preview(client, headers, _body([["a", "b"]], {0: "name_ar", 1: "name_ar"}))

    assert response.status_code == 422


async def test_an_unknown_field_name_is_refused(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)

    response = await _preview(client, headers, _body([["a", "b"]], {0: "name_ar", 1: "tenant_id"}))

    assert response.status_code == 422


# --- commit ------------------------------------------------------------------------


async def test_commit_creates_products_with_opening_stock(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    rows = [
        ["يوريا 46%", "كيلو", "450", "5", "40"],
        ["بذور خيار", "قطعة", "30", "10", "25"],
        ["سلة", "قطعة", "15", "", ""],
    ]

    response = await _commit(client, headers, _body(rows))

    assert response.status_code == 200, response.text
    assert response.json()["created"] == 3
    assert response.json()["opening_balances"] == 2
    assert await _inventory(client, headers) == {
        "يوريا 46%": Decimal("40"),
        "بذور خيار": Decimal("25"),
        "سلة": Decimal("0"),
    }
    listing = (await client.get("/api/v1/inventory?page_size=100", headers=headers)).json()["items"]
    urea = next(item for item in listing if item["name_ar"] == "يوريا 46%")
    assert urea["base_unit_code"] == "kilogram"
    assert Decimal(urea["minimum_stock"]) == Decimal("5")


async def test_importing_the_same_sheet_twice_creates_nothing_the_second_time(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    body = _body([["يوريا", "قطعة", "10", "", "5"], ["بذور", "قطعة", "20", "", "7"]])

    first = await _commit(client, headers, body)
    second = await _commit(client, headers, body)

    assert first.json()["created"] == 2
    assert second.status_code == 200
    assert second.json()["created"] == 0
    assert second.json()["skipped"] == 2
    assert await _inventory(client, headers) == {"يوريا": Decimal("5"), "بذور": Decimal("7")}


async def test_a_problem_row_stops_everything_unless_the_owner_chooses_to_skip_it(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    rows = [["جيد", "قطعة", "10", "", "5"], ["سيء", "قطعة", "abc", "", "5"]]

    refused = await _commit(client, headers, _body(rows))

    assert refused.status_code == 409
    assert refused.json()["error"]["message"] == "في الملف صفوف بها مشاكل. صحّحها أو اختر تجاهلها."
    assert await _inventory(client, headers) == {}  # nothing was created

    allowed = await _commit(client, headers, _body(rows, skip_errors=True))

    assert allowed.json()["created"] == 1
    assert await _inventory(client, headers) == {"جيد": Decimal("5")}


async def test_generated_codes_never_collide(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    await create_product_api(client, headers, sku="Z-00003", name_ar="موجود")

    await _commit(client, headers, _body([["أ", "قطعة", "", "", ""], ["ب", "قطعة", "", "", ""]]))
    await _commit(client, headers, _body([["ج", "قطعة", "", "", ""]]))

    products = (await client.get("/api/v1/products?page_size=100", headers=headers)).json()["items"]
    skus = sorted(p["sku"] for p in products)
    assert skus == ["Z-00003", "Z-00004", "Z-00005", "Z-00006"]


async def test_codes_and_barcodes_from_the_sheet_are_kept_and_checked(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    await create_product_api(client, headers, sku="UREA", name_ar="موجود", barcode="6221111111111")
    mapping = {0: "name_ar", 1: "sku", 2: "barcode"}
    rows = [
        ["جديد", "NEW-1", "6222222222222"],
        ["آخر", "UREA", ""],
        ["ثالث", "X-3", "6221111111111"],
    ]

    body = (await _preview(client, headers, _body(rows, mapping))).json()

    assert [r["status"] for r in body["rows"]] == ["create", "skip", "skip"]
    assert body["rows"][0]["sku"] == "NEW-1"


async def test_new_categories_and_brands_are_created_once_and_old_ones_are_reused(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    mapping = {0: "name_ar", 1: "category", 2: "brand"}
    rows = [
        ["أ", "بذور", "الشركة العربية"],
        ["ب", "بُذور", "الشركة العربية"],  # same category, other spelling
        ["ج", "أسمدة", ""],
    ]

    first = (await _commit(client, headers, _body(rows, mapping))).json()
    second = (
        await _commit(client, headers, _body([["د", "أسمدة", "الشركة العربية"]], mapping))
    ).json()

    assert (first["new_categories"], first["new_brands"]) == (2, 1)
    assert (second["new_categories"], second["new_brands"]) == (0, 0)
    categories = (await client.get("/api/v1/categories", headers=headers)).json()
    assert sorted(c["name_ar"] for c in categories) == ["أسمدة", "بذور"]


async def test_cost_is_ignored_without_the_cost_permission(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session, role=MembershipRole.MANAGER)
    mapping = {0: "name_ar", 1: "cost_price", 2: "sale_price"}

    preview = (await _preview(client, headers, _body([["سماد", "100", "150"]], mapping))).json()
    committed = await _commit(client, headers, _body([["سماد", "100", "150"]], mapping))

    assert any("التكلفة" in notice for notice in preview["notices"])
    assert committed.status_code == 200
    detail = (await client.get("/api/v1/products?page_size=10", headers=headers)).json()["items"][0]
    assert Decimal(detail["sale_price"]) == Decimal("150")
    assert detail.get("cost_price") in (None, "None")


async def test_the_owner_keeps_the_cost(client: AsyncClient, owner_session: AsyncSession) -> None:
    _, headers, tenant, _ = await seeded_login(client, owner_session)
    mapping = {0: "name_ar", 1: "cost_price"}

    await _commit(client, headers, _body([["سماد", "100"]], mapping))

    cost = (
        await owner_session.execute(
            text("SELECT cost_price FROM products WHERE tenant_id = :t"), {"t": tenant.id}
        )
    ).scalar_one()
    assert cost == Decimal("100.00")


async def test_the_chosen_default_unit_is_used_when_the_sheet_has_none(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    units = (await client.get("/api/v1/units", headers=headers)).json()
    bag = next(u["id"] for u in units if u["code"] == "bag")

    await _commit(client, headers, _body([["سماد", "", "", "", "4"]], default_unit_id=bag))

    listing = (await client.get("/api/v1/inventory?page_size=10", headers=headers)).json()["items"]
    assert listing[0]["base_unit_code"] == "bag"


async def test_balances_equal_movements_after_an_import(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, tenant, _ = await seeded_login(client, owner_session)
    rows = [[f"صنف {i}", "قطعة", "10", "", str(i + 1)] for i in range(5)]

    await _commit(client, headers, _body(rows))

    result = (
        await owner_session.execute(
            text(
                "SELECT count(*) AS n, bool_and(b.quantity = m.moved) AS same FROM"
                " inventory_balances b JOIN (SELECT product_id, sum(base_quantity) AS moved"
                " FROM stock_movements WHERE tenant_id = :t GROUP BY product_id) m"
                " ON m.product_id = b.product_id WHERE b.tenant_id = :t"
            ),
            {"t": tenant.id},
        )
    ).one()
    assert (result.n, result.same) == (5, True)


# --- access ------------------------------------------------------------------------


async def test_a_cashier_cannot_import(client: AsyncClient, owner_session: AsyncSession) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session, role=MembershipRole.CASHIER)

    assert (await _analyze(client, headers, _xlsx([["الصنف"], ["أ"]]))).status_code == 403
    assert (await _preview(client, headers, _body([["أ"]]))).status_code == 403
    assert (await _commit(client, headers, _body([["أ"]]))).status_code == 403
    assert (await client.get(f"{BASE}/template", headers=headers)).status_code == 403


async def test_a_storekeeper_can_import(client: AsyncClient, owner_session: AsyncSession) -> None:
    _, headers, _, _ = await seeded_login(
        client, owner_session, role=MembershipRole.INVENTORY_MANAGER
    )

    response = await _commit(client, headers, _body([["أ", "قطعة", "", "", "3"]]))

    assert response.status_code == 200
    assert response.json()["created"] == 1


async def test_one_shop_never_sees_or_affects_another(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, mine, _, _ = await seeded_login(client, owner_session, tenant_name="متجري")
    _, theirs, _, _ = await seeded_login(client, owner_session, tenant_name="متجر آخر")
    await create_product_api(client, theirs, sku="SAME", name_ar="يوريا")

    response = await _commit(client, mine, _body([["يوريا", "قطعة", "", "", "5"]]))

    assert response.json()["created"] == 1  # their "يوريا" does not make mine a duplicate
    assert await _inventory(client, mine) == {"يوريا": Decimal("5")}
    assert await _inventory(client, theirs) == {"يوريا": Decimal("0")}


async def test_too_many_rows_are_refused_on_preview_and_commit(
    client: AsyncClient, owner_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(importer_service, "MAX_ROWS", 3)
    _, headers, _, _ = await seeded_login(client, owner_session)
    body = _body([[f"صنف {i}"] for i in range(4)], {0: "name_ar"})

    assert (await _preview(client, headers, body)).status_code == 422
    assert (await _commit(client, headers, body)).status_code == 422


# --- template ----------------------------------------------------------------------


async def test_the_blank_template_is_a_readable_sheet_the_rules_fully_understand(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)

    download = await client.get(f"{BASE}/template", headers=headers)

    assert download.status_code == 200
    assert download.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "attachment" in download.headers["content-disposition"]
    data = read_sheet(download.content, "template.xlsx")
    assert len(data.rows) >= 2  # headers and one example row
    analyzed = await _analyze(client, headers, download.content)
    fields = [c["field"] for c in analyzed.json()["columns"]]
    assert None not in fields
    assert "name_ar" in fields and "quantity" in fields
    assert {c["source"] for c in analyzed.json()["columns"]} == {"rules"}
