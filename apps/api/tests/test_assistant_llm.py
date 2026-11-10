"""Groq client: request shape and model fallback."""

import json
from collections.abc import Callable

import httpx
import pytest

from app.modules.assistant.llm import AssistantUnavailable, GroqClient

OK_BODY = {"choices": [{"message": {"role": "assistant", "content": "تمام"}}]}
MESSAGES = [{"role": "user", "content": "فاضل كام يوريا؟"}]
TOOLS = [{"type": "function", "function": {"name": "low_stock", "parameters": {"type": "object"}}}]


Handler = Callable[[httpx.Request], httpx.Response]


def client_with(handler: Handler) -> tuple[GroqClient, list[dict]]:
    seen: list[dict] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(
            {"body": json.loads(request.content), "auth": request.headers.get("authorization")}
        )
        return handler(request)

    groq = GroqClient(
        api_key="k", models=["m1", "m2"], timeout=5, transport=httpx.MockTransport(record)
    )
    return groq, seen


async def test_uses_first_model_when_it_succeeds() -> None:
    groq, seen = client_with(lambda _: httpx.Response(200, json=OK_BODY))

    completion = await groq.complete(MESSAGES, TOOLS)

    assert completion.model == "m1"
    assert completion.message["content"] == "تمام"
    assert seen[0]["auth"] == "Bearer k"
    body = seen[0]["body"]
    assert body["model"] == "m1"
    assert body["temperature"] == 0.2
    assert body["max_completion_tokens"] == 600
    assert body["tools"] == TOOLS
    assert body["tool_choice"] == "auto"


@pytest.mark.parametrize("failure", ["429", "503", "timeout"])
async def test_falls_back_on_429_5xx_and_timeout(failure: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content)["model"] == "m1":
            if failure == "timeout":
                raise httpx.ReadTimeout("slow", request=request)
            return httpx.Response(int(failure), json={"error": {"message": "busy"}})
        return httpx.Response(200, json=OK_BODY)

    groq, _ = client_with(handler)

    completion = await groq.complete(MESSAGES, TOOLS)

    assert completion.model == "m2"


async def test_all_models_failing_raises_unavailable() -> None:
    groq, seen = client_with(lambda _: httpx.Response(500, json={}))

    with pytest.raises(AssistantUnavailable):
        await groq.complete(MESSAGES, TOOLS)

    assert [call["body"]["model"] for call in seen] == ["m1", "m2"]


async def test_tools_omitted_when_empty() -> None:
    groq, seen = client_with(lambda _: httpx.Response(200, json=OK_BODY))

    await groq.complete(MESSAGES, [])

    assert "tools" not in seen[0]["body"]
    assert "tool_choice" not in seen[0]["body"]


async def test_malformed_success_body_falls_back() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content)["model"] == "m1":
            return httpx.Response(200, json={"unexpected": True})
        return httpx.Response(200, json=OK_BODY)

    groq, _ = client_with(handler)

    assert (await groq.complete(MESSAGES, TOOLS)).model == "m2"
