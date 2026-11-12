"""Smart import routes. The file is sent as the raw request body (no multipart
dependency): ``POST /imports/analyze?filename=...`` with the bytes as content."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ForbiddenError, UnprocessableError
from app.infrastructure.db.session import get_session
from app.modules.assistant.llm import LLM
from app.modules.assistant.quota import QuotaExceeded, assistant_quota
from app.modules.assistant.router import get_llm
from app.modules.auth.dependencies import CurrentPrincipal, CurrentTenant, TenantContext
from app.modules.authorization.permissions import Permission
from app.modules.importer import service
from app.modules.importer.parser import MAX_BYTES, TOO_LARGE
from app.modules.importer.schemas import AnalyzeOut, CommitOut, ImportRequest, PreviewOut

router = APIRouter(prefix="/api/v1/imports", tags=["import"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
LLMDep = Annotated[LLM | None, Depends(get_llm)]
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


async def _importer(context: CurrentTenant) -> TenantContext:
    """Importing creates products and stock: it needs both permissions."""
    for permission in (Permission.PRODUCTS_CREATE, Permission.INVENTORY_ADJUST):
        if not context.allows(permission):
            raise ForbiddenError(
                "Your role does not allow this action", details={"permission": permission.value}
            )
    return context


Importer = Annotated[TenantContext, Depends(_importer)]


@router.post("/analyze", response_model=AnalyzeOut)
async def analyze(
    request: Request,
    context: Importer,
    llm: LLMDep,
    filename: Annotated[str, Query(min_length=1, max_length=255)],
    sheet: Annotated[str | None, Query(max_length=120)] = None,
) -> AnalyzeOut:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BYTES:
        raise UnprocessableError(TOO_LARGE)
    content = await request.body()
    if not content:
        raise UnprocessableError(service.EMPTY_UPLOAD)

    # One question of the shop's daily assistant allowance, only if it is used.
    asking: LLM | None = None
    if llm is not None:
        try:
            assistant_quota.consume(context.tenant.id, get_settings().assistant_daily_limit)
            asking = llm
        except QuotaExceeded:
            asking = None
    result = await service.analyze(content, filename, sheet, asking)
    if asking is not None and not result.assistant_used:
        assistant_quota.refund(context.tenant.id)
    return result


@router.post("/preview", response_model=PreviewOut)
async def preview(payload: ImportRequest, context: Importer, db: SessionDep) -> PreviewOut:
    return await service.preview(db, context, payload)


@router.post("/commit", response_model=CommitOut)
async def commit(
    payload: ImportRequest, context: Importer, principal: CurrentPrincipal, db: SessionDep
) -> CommitOut:
    return await service.commit(db, context, principal.user_id, payload)


@router.get("/template")
async def template(context: Importer) -> Response:
    content = await asyncio.to_thread(service.build_template)
    return Response(
        content=content,
        media_type=XLSX,
        headers={"Content-Disposition": 'attachment; filename="zain-products-template.xlsx"'},
    )
