"""The assistant's tool-calling loop.

prompt + recent turns → model → run the lookups it asks for → model …,
for at most MAX_TOOL_ROUNDS rounds, after which the model must answer with
no tools offered.
"""

import json
from dataclasses import dataclass
from typing import Any, Literal

from app.modules.assistant.llm import LLM
from app.modules.assistant.prompt import SYSTEM_PROMPT
from app.modules.assistant.tools import ToolContext, run_tool, tool_schemas

MAX_TOOL_ROUNDS = 4
MAX_TURNS = 10
# ≈ 4,000 tokens at ~3 characters per token for Arabic.
MAX_HISTORY_CHARS = 12_000

FALLBACK_REPLY = "مش قادر أجاوب على ده دلوقتي، جرّب تسأل بطريقة تانية."


@dataclass(frozen=True)
class Turn:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class Source:
    tool: str
    label: str


@dataclass(frozen=True)
class AgentReply:
    reply: str
    sources: list[Source]
    model: str
    tools_used: list[str]


def trim_history(history: list[Turn]) -> list[Turn]:
    """Last MAX_TURNS turns, then drop the oldest until under the character budget."""
    turns = history[-MAX_TURNS:]
    while len(turns) > 1 and sum(len(turn.content) for turn in turns) > MAX_HISTORY_CHARS:
        turns = turns[1:]
    return turns


def _echo(message: dict[str, Any]) -> dict[str, Any]:
    """The assistant turn sent back to the model: only the fields the API accepts."""
    return {
        "role": "assistant",
        "content": message.get("content") or "",
        "tool_calls": [
            {
                "id": call["id"],
                "type": "function",
                "function": {
                    "name": call["function"]["name"],
                    "arguments": call["function"].get("arguments") or "{}",
                },
            }
            for call in message["tool_calls"]
        ],
    }


async def answer(llm: LLM, ctx: ToolContext, history: list[Turn]) -> AgentReply:
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += [{"role": turn.role, "content": turn.content} for turn in trim_history(history)]
    schemas = tool_schemas(ctx.permissions)

    sources: list[Source] = []
    tools_used: list[str] = []
    model = ""

    for round_number in range(MAX_TOOL_ROUNDS + 1):
        offered = schemas if round_number < MAX_TOOL_ROUNDS else []
        completion = await llm.complete(messages, offered)
        model = completion.model
        message = completion.message
        calls = message.get("tool_calls") or []

        if not calls or not offered:
            text = (message.get("content") or "").strip()
            return AgentReply(text or FALLBACK_REPLY, sources, model, tools_used)

        messages.append(_echo(message))
        for call in calls:
            name = call["function"]["name"]
            outcome = await run_tool(name, call["function"].get("arguments") or "{}", ctx)
            tools_used.append(name)
            if outcome.label and Source(name, outcome.label) not in sources:
                sources.append(Source(name, outcome.label))
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(outcome.result, ensure_ascii=False),
                }
            )

    return AgentReply(FALLBACK_REPLY, sources, model, tools_used)  # pragma: no cover
