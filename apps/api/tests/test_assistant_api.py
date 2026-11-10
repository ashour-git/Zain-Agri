"""HTTP contract of the shop assistant endpoints."""

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.assistant.llm import AssistantUnavailable
from app.modules.assistant.router import get_llm
from tests.assistant_fakes import ScriptedLLM, reply, tool_call
from tests.support import seeded_login

Installer = Callable[[Any], Any]

CHAT = "/api/v1/assistant/chat"
STATUS = "/api/v1/assistant/status"


@pytest.fixture
def enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "groq_api_key", SecretStr("test-key"))


@pytest.fixture
def use_llm(test_app: FastAPI) -> Iterator[Installer]:
    """Route the endpoint's LLM to a scripted fake for this test's app."""

    def install(llm: Any) -> Any:
        test_app.dependency_overrides[get_llm] = lambda: llm
        return llm

    yield install
    test_app.dependency_overrides.clear()


def ask(text: str) -> dict[str, Any]:
    return {"messages": [{"role": "user", "content": text}]}


async def test_disabled_without_key(
    client: AsyncClient, owner_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "groq_api_key", None)
    _, headers, _, _ = await seeded_login(client, owner_session)

    status = await client.get(STATUS, headers=headers)
    chat = await client.post(CHAT, json=ask("أهلاً"), headers=headers)

    assert status.json() == {"enabled": False, "remaining_today": 0}
    assert chat.status_code == 404
    assert chat.json()["error"]["code"] == "assistant_disabled"


@pytest.mark.usefixtures("enabled")
async def test_chat_returns_reply_sources_and_remaining(
    client: AsyncClient, owner_session: AsyncSession, use_llm: Installer
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    use_llm(ScriptedLLM(tool_call("low_stock", {}), reply("مفيش نواقص.")))
    limit = get_settings().assistant_daily_limit

    response = await client.post(CHAT, json=ask("إيه اللي ناقص؟"), headers=headers)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "reply": "مفيش نواقص.",
        "sources": [{"tool": "low_stock", "label": "الأصناف تحت الحد"}],
        "remaining_today": limit - 1,
    }
    status = await client.get(STATUS, headers=headers)
    assert status.json() == {"enabled": True, "remaining_today": limit - 1}


@pytest.mark.usefixtures("enabled")
async def test_message_length_boundary(
    client: AsyncClient, owner_session: AsyncSession, use_llm: Installer
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    use_llm(ScriptedLLM(reply("تمام")))

    accepted = await client.post(CHAT, json=ask("ا" * 500), headers=headers)
    rejected = await client.post(CHAT, json=ask("ا" * 501), headers=headers)

    assert accepted.status_code == 200
    assert rejected.status_code == 422


@pytest.mark.usefixtures("enabled")
async def test_last_turn_must_be_user(
    client: AsyncClient, owner_session: AsyncSession, use_llm: Installer
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    use_llm(ScriptedLLM(reply("تمام")))
    body = {
        "messages": [{"role": "user", "content": "سؤال"}, {"role": "assistant", "content": "رد"}]
    }

    response = await client.post(CHAT, json=body, headers=headers)

    assert response.status_code == 422


@pytest.mark.usefixtures("enabled")
async def test_quota_exceeded_returns_429_with_retry_after(
    client: AsyncClient,
    owner_session: AsyncSession,
    use_llm: Installer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "assistant_daily_limit", 1)
    _, headers, _, _ = await seeded_login(client, owner_session)
    use_llm(ScriptedLLM(reply("تمام")))

    first = await client.post(CHAT, json=ask("سؤال"), headers=headers)
    second = await client.post(CHAT, json=ask("سؤال تاني"), headers=headers)

    assert first.status_code == 200
    assert first.json()["remaining_today"] == 0
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "assistant_quota_exceeded"
    assert int(second.headers["Retry-After"]) >= 1


@pytest.mark.usefixtures("enabled")
async def test_all_models_down_returns_503(
    client: AsyncClient, owner_session: AsyncSession, use_llm: Installer
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    use_llm(ScriptedLLM(AssistantUnavailable()))

    response = await client.post(CHAT, json=ask("سؤال"), headers=headers)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "assistant_unavailable"


@pytest.mark.usefixtures("enabled")
async def test_audit_row_has_no_question_text(
    client: AsyncClient, owner_session: AsyncSession, use_llm: Installer
) -> None:
    _, headers, _, _ = await seeded_login(client, owner_session)
    use_llm(ScriptedLLM(tool_call("low_stock", {}), reply("تمام")))
    secret_question = "سؤال سري عن سماد اليوريا"

    await client.post(CHAT, json=ask(secret_question), headers=headers)
    audit = await client.get("/api/v1/audit?entity_type=assistant", headers=headers)

    assert audit.status_code == 200
    row = audit.json()["items"][0]
    assert row["action"] == "assistant.asked"
    assert row["meta"]["tools"] == ["low_stock"]
    assert row["meta"]["model"] == "fake-model"
    assert "latency_ms" in row["meta"]
    assert secret_question not in audit.text


async def test_requires_authentication(client: AsyncClient) -> None:
    response = await client.post(CHAT, json=ask("سؤال"))

    assert response.status_code == 401
