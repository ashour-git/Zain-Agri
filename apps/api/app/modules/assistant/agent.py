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
# A model may ask for several lookups at once; more than this per round is refused.
MAX_CALLS_PER_ROUND = 5
# Hard ceiling on database work for one question, across all rounds.
MAX_LOOKUPS_PER_QUESTION = 12
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


def _valid_calls(raw: Any) -> list[dict[str, Any]]:
    """Tool calls with the fields we rely on; anything malformed is dropped."""
    calls = []
    for call in raw if isinstance(raw, list) else []:
        function = call.get("function") if isinstance(call, dict) else None
        if (
            isinstance(call.get("id") if isinstance(call, dict) else None, str)
            and isinstance(function, dict)
            and isinstance(function.get("name"), str)
        ):
            arguments = function.get("arguments")
            calls.append(
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {
                        "name": function["name"],
                        "arguments": arguments if isinstance(arguments, str) else "{}",
                    },
                }
            )
    return calls


def _tool_message(call_id: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": json.dumps(result, ensure_ascii=False, separators=(",", ":")),
    }


async def _release_connection(ctx: ToolContext) -> None:
    """End the read transaction before a slow model call.

    Waiting on the model while holding a pooled connection lets a slow
    provider exhaust the pool for every other request. The tenant context is
    re-applied automatically when the next transaction begins.
    """
    if ctx.db.in_transaction():
        await ctx.db.commit()


async def answer(llm: LLM, ctx: ToolContext, history: list[Turn]) -> AgentReply:
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += [{"role": turn.role, "content": turn.content} for turn in trim_history(history)]
    schemas = tool_schemas(ctx.permissions)

    sources: list[Source] = []
    tools_used: list[str] = []
    model = ""

    for round_number in range(MAX_TOOL_ROUNDS + 1):
        offered = schemas if round_number < MAX_TOOL_ROUNDS else []
        await _release_connection(ctx)
        completion = await llm.complete(messages, offered)
        model = completion.model
        message = completion.message
        requested = message.get("tool_calls") or []
        calls = _valid_calls(requested)

        if not requested or not offered:
            text = (message.get("content") or "").strip()
            return AgentReply(text or FALLBACK_REPLY, sources, model, tools_used)
        if not calls:
            # Every call was malformed: ask again rather than crash.
            continue

        messages.append(
            {"role": "assistant", "content": message.get("content") or "", "tool_calls": calls}
        )
        for index, call in enumerate(calls):
            if index >= MAX_CALLS_PER_ROUND:
                messages.append(_tool_message(call["id"], {"error": "too_many_calls"}))
                continue
            if len(tools_used) >= MAX_LOOKUPS_PER_QUESTION:
                messages.append(_tool_message(call["id"], {"error": "lookup_limit_reached"}))
                continue
            name = call["function"]["name"]
            outcome = await run_tool(name, call["function"]["arguments"], ctx)
            tools_used.append(name)
            if outcome.label and Source(name, outcome.label) not in sources:
                sources.append(Source(name, outcome.label))
            messages.append(_tool_message(call["id"], outcome.result))

    await _release_connection(ctx)
    return AgentReply(FALLBACK_REPLY, sources, model, tools_used)
