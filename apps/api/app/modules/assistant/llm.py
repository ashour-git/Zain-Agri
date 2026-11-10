"""Groq chat completions over its OpenAI-compatible HTTP API.

Models are tried in order. A busy (429), failing (5xx or other non-2xx),
slow or malformed response moves on to the next model, so one model's
free-tier limit does not take the assistant down. Message content is never
logged.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

logger = logging.getLogger(__name__)

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
TEMPERATURE = 0.2
MAX_COMPLETION_TOKENS = 600
# Idle connections are kept this long so the next question skips DNS and TLS.
KEEPALIVE_SECONDS = 300.0
# A 429 asking us to wait at most this long is retried once on the same model;
# longer waits move straight to the next model.
MAX_RETRY_WAIT_SECONDS = 8.0


def _error_code(response: httpx.Response) -> str | None:
    """Groq's short error code (e.g. tool_use_failed). Never the message: it can echo user data."""
    try:
        code = response.json()["error"]["code"]
    except (ValueError, KeyError, TypeError):
        return None
    return code if isinstance(code, str) else None


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return max(0.0, float(response.headers["retry-after"]))
    except (KeyError, ValueError):
        return None


class AssistantUnavailable(Exception):
    """Every configured model failed."""


@dataclass(frozen=True)
class Completion:
    message: dict[str, Any]
    model: str


class LLM(Protocol):
    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> Completion: ...


class GroqClient:
    def __init__(
        self,
        *,
        api_key: str,
        models: list[str],
        timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._models = models
        self._timeout = timeout
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    def _http(self) -> httpx.AsyncClient:
        # One long-lived connection: opening a new one costs a DNS lookup and a
        # TLS handshake every question (measured at ~15 s on a slow resolver).
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
                limits=httpx.Limits(keepalive_expiry=KEEPALIVE_SECONDS),
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _post(self, client: httpx.AsyncClient, body: dict[str, Any]) -> httpx.Response:
        return await client.post(
            GROQ_CHAT_URL, json=body, headers={"Authorization": f"Bearer {self._api_key}"}
        )

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> Completion:
        client = self._http()
        for model in self._models:
            body: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "temperature": TEMPERATURE,
                "max_completion_tokens": MAX_COMPLETION_TOKENS,
            }
            if tools:
                body["tools"] = tools
                body["tool_choice"] = "auto"

            try:
                response = await self._post(client, body)
                wait = _retry_after(response)
                if (
                    response.status_code == 429
                    and wait is not None
                    and wait <= MAX_RETRY_WAIT_SECONDS
                ):
                    await asyncio.sleep(wait)
                    response = await self._post(client, body)
            except httpx.HTTPError as exc:
                logger.warning(
                    "assistant_model_failed",
                    extra={"model": model, "reason": type(exc).__name__},
                )
                continue

            if not response.is_success:
                logger.warning(
                    "assistant_model_failed",
                    extra={
                        "model": model,
                        "status_code": response.status_code,
                        "error_code": _error_code(response),
                    },
                )
                continue

            try:
                message = response.json()["choices"][0]["message"]
            except (ValueError, KeyError, IndexError, TypeError):
                logger.warning(
                    "assistant_model_failed", extra={"model": model, "reason": "bad_body"}
                )
                continue

            return Completion(message=message, model=model)

        raise AssistantUnavailable
