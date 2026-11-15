"""Public, login-free invoice link (the page a customer opens from WhatsApp)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.client_ip import client_ip
from app.core.errors import TooManyRequestsError
from app.core.ratelimit import auth_limiter
from app.infrastructure.db.session import get_session
from app.modules.sales import sharing
from app.modules.sales.schemas import PublicInvoiceOut

router = APIRouter(prefix="/api/v1/public", tags=["public"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

LINK_LIMIT = 60
LINK_WINDOW_SECONDS = 300


@router.get("/invoices/{token}", response_model=PublicInvoiceOut)
async def public_invoice(
    token: Annotated[str, Path(min_length=16, max_length=100)],
    request: Request,
    response: Response,
    db: SessionDep,
) -> PublicInvoiceOut:
    key = f"invoice-link:{client_ip(request)}"
    if not auth_limiter.allow(key, limit=LINK_LIMIT, window_seconds=LINK_WINDOW_SECONDS):
        raise TooManyRequestsError(
            "Too many attempts, please try again later",
            retry_after=auth_limiter.retry_after(key, window_seconds=LINK_WINDOW_SECONDS),
        )
    response.headers["X-Robots-Tag"] = "noindex"
    response.headers["Cache-Control"] = "no-store"
    return await sharing.public_invoice(db, token)
