"""Shared test fixtures.

Tests run against a dedicated database (TEST_DATABASE_NAME) that is dropped
and re-migrated once per session, so assertions never see leftover state.
"""

import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alembic import command

# Must run before pytest-asyncio creates its loop: psycopg async cannot use the
# Proactor event loop that Windows picks by default.
if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
TEST_DB_NAME = os.environ.get("TEST_DATABASE_NAME", "zain_agri_test")


def _with_database(url: str, name: str) -> str:
    return make_url(url).set(database=name).render_as_string(hide_password=False)


def _apply(engine_url: str, statement: str) -> None:
    engine = create_engine(engine_url)
    try:
        with engine.begin() as conn:
            conn.execute(text(statement))
    finally:
        engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    """Recreate the test database schema and run all migrations once."""
    from app.core.config import get_settings
    from app.infrastructure.db import session as db

    settings = get_settings()
    app_url = _with_database(settings.database_url, TEST_DB_NAME)
    owner_url = _with_database(settings.alembic_url, TEST_DB_NAME)

    os.environ["DATABASE_URL"] = app_url
    os.environ["MIGRATION_DATABASE_URL"] = owner_url
    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db.get_session_factory.cache_clear()

    _apply(owner_url, "DROP SCHEMA IF EXISTS public CASCADE")
    _apply(owner_url, "CREATE SCHEMA public")

    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    command.upgrade(config, "head")

    grants = (REPO_ROOT / "infrastructure" / "db" / "grants.sql").read_text(encoding="utf-8")
    _apply(owner_url, grants)


@pytest_asyncio.fixture
async def owner_session() -> AsyncIterator[AsyncSession]:
    """Owner-role session. Bypasses RLS — used only to seed fixtures."""
    from app.core.config import get_settings

    engine = create_async_engine(get_settings().alembic_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Runtime-role session — the same role and RLS rules the API uses."""
    from app.infrastructure.db.session import get_session_factory

    async with get_session_factory()() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from app.main import create_app

    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
