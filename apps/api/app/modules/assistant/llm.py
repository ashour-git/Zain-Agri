"""Groq chat completions over its OpenAI-compatible HTTP API.

Models are tried in order. A busy (429), failing (5xx or other non-2xx),
slow or malformed response moves on to the next model, so one model's
free-tier limit does not take the assistant down. Message content is never
logged.
"""

import logging
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

logger = logging.getLogger(__name__)

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
TEMPERATURE = 0.2
MAX_COMPLETION_TOKENS = 600


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

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> Completion:
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
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
                    response = await client.post(
                        GROQ_CHAT_URL,
                        json=body,
                        headers={"Authorization": f"Bearer {self._api_key}"},
                    )
                except httpx.HTTPError as exc:
                    logger.warning(
                        "assistant_model_failed",
                        extra={"model": model, "reason": type(exc).__name__},
                    )
                    continue

                if not response.is_success:
                    logger.warning(
                        "assistant_model_failed",
                        extra={"model": model, "status_code": response.status_code},
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
