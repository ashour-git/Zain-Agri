"""Server-Timing header: where a request spent its time.

Shows in the browser's network panel, and the same numbers go to the access
log, so slow requests can be explained (new database connections versus
slow queries) without guessing.
"""

import re

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.support import seeded_login

ENTRY = re.compile(r'(?P<name>[\w-]+);dur=(?P<dur>\d+(?:\.\d+)?)(?:;desc="(?P<desc>[^"]*)")?')


def _entries(header: str) -> dict[str, tuple[float, str | None]]:
    return {m["name"]: (float(m["dur"]), m["desc"]) for m in ENTRY.finditer(header)}


async def test_database_request_reports_query_and_connection_time(
    client: AsyncClient, owner_session: AsyncSession
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)

    response = await client.get("/api/v1/auth/me", headers=headers)

    assert response.status_code == 200
    entries = _entries(response.headers["server-timing"])
    assert {"db", "db-connect", "total"} <= entries.keys()
    db_ms, db_desc = entries["db"]
    assert db_ms > 0
    assert db_desc is not None and re.fullmatch(r"\d+ queries", db_desc)
    assert int(db_desc.split()[0]) >= 1
    _, connect_desc = entries["db-connect"]
    assert connect_desc is not None and re.fullmatch(r"\d+ new", connect_desc)
    assert entries["total"][0] >= db_ms


async def test_request_without_database_reports_zero_queries(client: AsyncClient) -> None:
    response = await client.get("/health/live")

    entries = _entries(response.headers["server-timing"])
    assert entries["db"] == (0.0, "0 queries")
    assert entries["db-connect"] == (0.0, "0 new")
