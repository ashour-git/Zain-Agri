"""Shop assistant endpoints: one chat call, one status call.

Nothing is stored except an audit row (tools used, model, latency); the
question text is never logged.
"""

import asyncio
import time
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import (
    AssistantDisabledError,
    AssistantQuotaError,
    AssistantUnavailableError,
    RequestValidationFailed,
)
from app.infrastructure.db.session import get_session
from app.modules.assistant.agent import Turn, answer
from app.modules.assistant.llm import LLM, AssistantUnavailable, GroqClient
from app.modules.assistant.quota import QuotaExceeded, assistant_quota
from app.modules.assistant.schemas import ChatIn, ChatOut, SourceOut, StatusOut
from app.modules.assistant.tools import ToolContext
from app.modules.audit import service as audit
from app.modules.auth.dependencies import CurrentPrincipal, CurrentTenant

router = APIRouter(prefix="/api/v1/assistant", tags=["assistant"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

DISABLED_MESSAGE = "المساعد غير مفعّل لهذا المتجر."
QUOTA_MESSAGE = "خلصت أسئلة النهارده، بتتجدد الساعة 12 بالليل."
UNAVAILABLE_MESSAGE = "المساعد مش متاح دلوقتي، جرّب كمان شوية."
LAST_TURN_MESSAGE = "آخر رسالة لازم تكون سؤال من المستخدم."

# The whole question: every model call and lookup, fallbacks included.
ANSWER_DEADLINE_SECONDS = 45.0


# One client per process, so its open connection is reused between questions.
_shared: tuple[tuple[str, tuple[str, ...], float], GroqClient] | None = None


def get_llm() -> LLM | None:
    global _shared
    settings = get_settings()
    if not settings.assistant_enabled or settings.groq_api_key is None:
        return None
    key = (
        settings.groq_api_key.get_secret_value(),
        tuple(settings.assistant_model_list),
        settings.assistant_timeout_seconds,
    )
    if _shared is None or _shared[0] != key:
        _shared = (key, GroqClient(api_key=key[0], models=list(key[1]), timeout=key[2]))
    return _shared[1]


async def close_llm() -> None:
    """Called on shutdown to close the shared connection."""
    global _shared
    if _shared is not None:
        await _shared[1].aclose()
        _shared = None


LLMDep = Annotated[LLM | None, Depends(get_llm)]


@router.get("/status", response_model=StatusOut)
async def assistant_status(context: CurrentTenant, settings: SettingsDep) -> StatusOut:
    if not settings.assistant_enabled:
        return StatusOut(enabled=False, remaining_today=0)
    return StatusOut(
        enabled=True,
        remaining_today=assistant_quota.remaining(
            context.tenant.id, settings.assistant_daily_limit
        ),
    )


@router.post("/chat", response_model=ChatOut)
async def chat(
    payload: ChatIn,
    context: CurrentTenant,
    principal: CurrentPrincipal,
    db: SessionDep,
    settings: SettingsDep,
    llm: LLMDep,
) -> ChatOut:
    if not settings.assistant_enabled or llm is None:
        raise AssistantDisabledError(DISABLED_MESSAGE)
    if payload.messages[-1].role != "user":
        raise RequestValidationFailed(LAST_TURN_MESSAGE)

    try:
        remaining = assistant_quota.consume(context.tenant.id, settings.assistant_daily_limit)
    except QuotaExceeded as exc:
        raise AssistantQuotaError(QUOTA_MESSAGE, retry_after=exc.retry_after) from exc

    started = time.perf_counter()
    ctx = ToolContext(db=db, tenant_id=context.tenant.id, permissions=context.permissions)
    history = [Turn(role=turn.role, content=turn.content) for turn in payload.messages]
    try:
        async with asyncio.timeout(ANSWER_DEADLINE_SECONDS):
            result = await answer(llm, ctx, history)
    except (AssistantUnavailable, TimeoutError) as exc:
        # Not the shop's fault: give the question back.
        assistant_quota.refund(context.tenant.id)
        raise AssistantUnavailableError(UNAVAILABLE_MESSAGE) from exc

    await audit.record(
        db,
        tenant_id=context.tenant.id,
        actor_id=principal.user_id,
        action="assistant.asked",
        entity_type="assistant",
        meta={
            "tools": result.tools_used,
            "model": result.model,
            "latency_ms": int((time.perf_counter() - started) * 1000),
        },
    )
    await db.commit()

    return ChatOut(
        reply=result.reply,
        sources=[SourceOut(tool=source.tool, label=source.label) for source in result.sources],
        remaining_today=remaining,
    )
