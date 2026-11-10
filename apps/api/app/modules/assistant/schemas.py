"""Shop assistant HTTP contracts."""

from typing import Literal

from pydantic import BaseModel, Field

MAX_MESSAGE_CHARS = 500


class TurnIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


class ChatIn(BaseModel):
    messages: list[TurnIn] = Field(min_length=1, max_length=50)


class SourceOut(BaseModel):
    tool: str
    label: str


class ChatOut(BaseModel):
    reply: str
    sources: list[SourceOut]
    remaining_today: int


class StatusOut(BaseModel):
    enabled: bool
    remaining_today: int
