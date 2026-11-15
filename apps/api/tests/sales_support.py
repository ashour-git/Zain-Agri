"""Helpers for sales tests."""

import uuid
from decimal import Decimal
from typing import Any

from httpx import AsyncClient

from tests.support import adjust_api, create_product_api, unit_id

SALES = "/api/v1/sales"


async def stocked_product(
    client: AsyncClient,
    headers: dict[str, str],
    quantity: str = "10",
    **product: Any,
) -> dict[str, Any]:
    created = await create_product_api(client, headers, **product)
    if Decimal(quantity) > 0 and not product.get("tracks_batches"):
        await adjust_api(
            client,
            headers,
            product_id=created["id"],
            quantity=quantity,
            unit_code=product.get("base_unit", "piece"),
        )
    return created


def sale_body(
    lines: list[dict[str, Any]],
    *,
    paid: str | None = None,
    customer_id: str | None = None,
    discount: str = "0",
    key: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "lines": lines,
        "discount": discount,
        "customer_id": customer_id,
        "idempotency_key": key or f"sale-{uuid.uuid4().hex}",
    }
    if paid is not None:
        body["paid"] = paid
    return body


def line(product: dict[str, Any], quantity: str = "1", **extra: Any) -> dict[str, Any]:
    return {"product_id": product["id"], "quantity": quantity, **extra}


async def sell(
    client: AsyncClient, headers: dict[str, str], body: dict[str, Any], expected: int = 201
) -> dict[str, Any]:
    response = await client.post(SALES, json=body, headers=headers)
    assert response.status_code == expected, response.text
    result: dict[str, Any] = response.json()
    return result


async def balance_of(client: AsyncClient, headers: dict[str, str], product_id: str) -> Decimal:
    items = (await client.get("/api/v1/inventory?page_size=100", headers=headers)).json()["items"]
    return Decimal(next(i for i in items if i["product_id"] == product_id)["quantity"])


async def add_conversion(
    client: AsyncClient,
    headers: dict[str, str],
    product_id: str,
    from_code: str,
    to_code: str,
    factor: str,
) -> None:
    response = await client.post(
        f"/api/v1/products/{product_id}/conversions",
        json={
            "from_unit_id": str(unit_id(from_code)),
            "to_unit_id": str(unit_id(to_code)),
            "factor": factor,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
