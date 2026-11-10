"""Test double for the assistant's LLM: replays a script and records every call."""

import copy
import json
from typing import Any

from app.modules.assistant.llm import Completion

Step = dict[str, Any] | Exception


def reply(text: str) -> dict[str, Any]:
    return {"role": "assistant", "content": text}


def tool_call(name: str, arguments: dict[str, Any] | str, call_id: str = "c1") -> dict[str, Any]:
    raw = arguments if isinstance(arguments, str) else json.dumps(arguments, ensure_ascii=False)
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": call_id, "type": "function", "function": {"name": name, "arguments": raw}}
        ],
    }


class ScriptedLLM:
    """Returns the scripted messages in order; once exhausted, repeats the last one."""

    def __init__(self, *script: Step, model: str = "fake-model") -> None:
        self.script = list(script)
        self.model = model
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> Completion:
        self.calls.append({"messages": copy.deepcopy(messages), "tools": copy.deepcopy(tools)})
        step = self.script[min(len(self.calls), len(self.script)) - 1]
        if isinstance(step, Exception):
            raise step
        return Completion(message=step, model=self.model)

    def sent_text(self) -> str:
        """Everything that would have left the server, as one string."""
        return json.dumps(self.calls, ensure_ascii=False)
