"""Per-shop invoice and return numbers: 1, 2, 3... never repeated, never skipped.

One statement takes the next number and locks the counter row until the
transaction ends, so concurrent sales wait for each other instead of sharing a
number, and a rolled-back sale gives its number back.
"""

import uuid
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

CounterName = Literal["invoice", "return"]

_NEXT = text(
    """
    INSERT INTO shop_counters (tenant_id, name, value) VALUES (:tenant_id, :name, 1)
    ON CONFLICT (tenant_id, name) DO UPDATE SET value = shop_counters.value + 1
    RETURNING value
    """
)


async def next_number(db: AsyncSession, tenant_id: uuid.UUID, name: CounterName) -> int:
    result = await db.execute(_NEXT, {"tenant_id": tenant_id, "name": name})
    value: int = result.scalar_one()
    return value
