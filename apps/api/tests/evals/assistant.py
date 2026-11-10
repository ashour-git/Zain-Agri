"""Live evaluation of the shop assistant against real Groq.

    uv run python -m tests.evals.assistant [--model MODEL] [--model MODEL2]

Seeds a fresh shop into the *test* database (run `pytest` once first so it is
migrated), then asks every question in assistant_cases.json through the real
HTTP endpoint: auth, permissions, lookups, prompt and model together.
Uses quota from your Groq key; not part of the default test run.
"""

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.engine import make_url

CASES = Path(__file__).with_name("assistant_cases.json")
TEST_DB_NAME = os.environ.get("TEST_DATABASE_NAME", "zain_agri_test")


def _point_at_test_database() -> None:
    from app.core.config import get_settings

    settings = get_settings()
    for env, url in (
        ("DATABASE_URL", settings.database_url),
        ("MIGRATION_DATABASE_URL", settings.alembic_url),
    ):
        os.environ[env] = make_url(url).set(database=TEST_DB_NAME).render_as_string(False)
    os.environ["ASSISTANT_DAILY_LIMIT"] = "1000"
    get_settings.cache_clear()


async def _seed(client: Any, owner_session: Any) -> dict[str, dict[str, str]]:
    from app.modules.identity.models import MembershipRole
    from tests.support import (
        adjust_api,
        auth_header,
        create_product_api,
        login,
        make_membership,
        make_user,
        seeded_login,
    )

    _, owner, tenant, _ = await seeded_login(
        client, owner_session, tenant_name=f"تقييم {uuid.uuid4().hex[:6]}"
    )

    async def product(
        name: str, unit: str, qty: str, minimum: str, price: str, **extra: Any
    ) -> str:
        body = await create_product_api(
            client,
            owner,
            name_ar=name,
            base_unit=unit,
            minimum_stock=minimum,
            sale_price=price,
            cost_price=extra.pop("cost", None),
            **extra,
        )
        if qty != "0":
            await adjust_api(client, owner, product_id=body["id"], quantity=qty, unit_code=unit)
        return str(body["id"])

    urea = await product("سماد يوريا 46%", "bag", "12", "20", "950.00", cost="800.00")
    await adjust_api(
        client,
        owner,
        product_id=urea,
        movement_type="adjustment_out",
        quantity="2",
        unit_code="bag",
        reason="شيكارتين مقطوعين",
    )
    await product("بذور طماطم هجين", "pack", "4", "10", "85.00")
    await product("سماد سوبر فوسفات", "bag", "40", "10", "700.00")
    await product("مبيد حشري لامبدا", "bottle", "0", "5", "120.00")
    copper = await product("مبيد فطري كوبر", "bottle", "0", "5", "150.00", tracks_batches=True)
    batch = await client.post(
        "/api/v1/inventory/batches",
        json={
            "product_id": copper,
            "batch_number": "COPPER-01",
            "expiry_date": (date.today() + timedelta(days=20)).isoformat(),
        },
        headers=owner,
    )
    batch.raise_for_status()
    await adjust_api(
        client,
        owner,
        product_id=copper,
        movement_type="adjustment_in",
        quantity="3",
        unit_code="bottle",
        batch_id=batch.json()["id"],
    )

    cashier_user = await make_user(owner_session)
    await make_membership(
        owner_session, tenant=tenant, user=cashier_user, role=MembershipRole.CASHIER
    )
    await owner_session.commit()
    cashier = auth_header(await login(client, cashier_user.email))
    return {"owner": owner, "cashier": cashier}


def _check(case: dict[str, Any], body: dict[str, Any]) -> tuple[bool, list[str]]:
    problems: list[str] = []
    reply = body.get("reply", "")
    used = [source["tool"] for source in body.get("sources", [])]
    expected = case["expected_tools"]
    if expected and not set(used) & set(expected):
        problems.append(f"tools {used} ∌ {expected}")
    for alternatives in case["must_contain"]:
        if not any(option in reply for option in alternatives):
            problems.append(f"missing {alternatives}")
    for forbidden in case["must_not_contain"]:
        if forbidden in reply:
            problems.append(f"forbidden «{forbidden}»")
    return not problems, problems


async def run(models: list[str], pause: float) -> None:
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config import get_settings
    from app.infrastructure.db import session as db
    from app.main import create_app

    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    for model in models:
        os.environ["ASSISTANT_MODELS"] = model
        get_settings.cache_clear()
        db.get_engine.cache_clear()
        db.get_session_factory.cache_clear()

        engine = create_async_engine(get_settings().alembic_url)
        async with (
            async_sessionmaker(engine, expire_on_commit=False)() as owner_session,
            AsyncClient(
                transport=ASGITransport(app=create_app()),
                base_url="http://localhost:3000",
                headers={"Origin": "http://localhost:3000"},
                timeout=120,
            ) as client,
        ):
            people = await _seed(client, owner_session)
            print(f"\n===== {model} =====")
            passed = 0
            for index, case in enumerate(cases, start=1):
                if index > 1 and pause:
                    # Free tier: 8k tokens/min per model. Pace so we measure quality, not limits.
                    await asyncio.sleep(pause)
                started = time.perf_counter()
                response = await client.post(
                    "/api/v1/assistant/chat",
                    json={"messages": [{"role": "user", "content": case["question"]}]},
                    headers=people[case["role"]],
                )
                seconds = time.perf_counter() - started
                if response.status_code != 200:
                    print(f"{index:>2} FAIL HTTP {response.status_code} {case['question']}")
                    print(f"     {response.text[:200]}")
                    continue
                body = response.json()
                ok, problems = _check(case, body)
                passed += ok
                used = [source["tool"] for source in body["sources"]]
                print(f"{index:>2} {'PASS' if ok else 'FAIL'} {seconds:4.1f}s {case['question']}")
                print(f"     tools={used} {'; '.join(problems)}")
                print(f"     → {body['reply'][:220].replace(chr(10), ' ')}")
            print(f"score {passed}/{len(cases)}")
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", action="append", help="model id; repeat to compare")
    parser.add_argument(
        "--pause", type=float, default=20.0, help="seconds between questions (free-tier pacing)"
    )
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    if not os.environ.get("GROQ_API_KEY"):
        from app.core.config import get_settings

        if not get_settings().assistant_enabled:
            sys.exit("GROQ_API_KEY is not set (environment or .env); nothing to evaluate.")

    _point_at_test_database()
    from app.core.config import get_settings

    models = args.model or get_settings().assistant_model_list
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run(models, args.pause))


if __name__ == "__main__":
    main()
