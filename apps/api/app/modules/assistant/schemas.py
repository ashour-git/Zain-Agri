"""Shop assistant HTTP contracts."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

# What a person may type. Earlier assistant replies (tables, lists) are sent
# back as history and are allowed to be much longer.
MAX_QUESTION_CHARS = 500
MAX_REPLY_CHARS = 4000


class TurnIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_REPLY_CHARS)

    @model_validator(mode="after")
    def _questions_are_short(self) -> "TurnIn":
        if self.role == "user" and len(self.content) > MAX_QUESTION_CHARS:
            raise ValueError(f"A question may be at most {MAX_QUESTION_CHARS} characters")
        return self


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
