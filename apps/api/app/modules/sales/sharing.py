"""Shareable invoice links for WhatsApp: a secret URL anyone can open.

The token is an HMAC of the invoice id and its share version under the app
secret, so sharing again (from any device) returns the same link; revoking
bumps the version, which kills the link and makes the next one different.
Only the sha256 of the token is stored. The public read finds the shop
through a narrow SECURITY DEFINER lookup, then reads the invoice under that
shop's RLS context, and never returns a phone or balance.
"""

import base64
import hashlib
import hmac
import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import NotFoundError
from app.modules.auth.dependencies import TenantContext
from app.modules.identity.models import Tenant
from app.modules.sales import service
from app.modules.sales.models import SalesInvoice
from app.modules.sales.schemas import PublicInvoiceOut, PublicLineOut, ShareOut
from app.modules.tenancy.context import set_tenant_context

LINK_NOT_FOUND = "This invoice link is not valid"

_LOOKUP = text("SELECT tenant_id, invoice_id FROM app_invoice_by_share_token(:h)")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _token(settings: Settings, invoice: SalesInvoice) -> str:
    message = f"invoice-link:{invoice.id}:{invoice.share_version}".encode()
    key = settings.jwt_secret_key.get_secret_value().encode()
    digest = hmac.new(key, message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


async def _invoice(db: AsyncSession, tenant_id: uuid.UUID, invoice_id: uuid.UUID) -> SalesInvoice:
    invoice = await db.scalar(
        select(SalesInvoice).where(
            SalesInvoice.tenant_id == tenant_id, SalesInvoice.id == invoice_id
        )
    )
    if invoice is None:
        raise NotFoundError(service.NOT_FOUND)
    return invoice


async def share(
    db: AsyncSession,
    context: TenantContext,
    actor_id: uuid.UUID,
    invoice_id: uuid.UUID,
    settings: Settings,
) -> ShareOut:
    # Same visibility as reading it: a cashier shares only their own invoices.
    await service.get_visible_sale(db, context, actor_id, invoice_id)
    invoice = await _invoice(db, context.tenant.id, invoice_id)
    token = _token(settings, invoice)
    if invoice.share_token_hash != _hash(token):
        invoice.share_token_hash = _hash(token)
        await db.commit()
    return ShareOut(url=f"{settings.public_app_url.rstrip('/')}/i/{token}")


async def revoke(db: AsyncSession, context: TenantContext, invoice_id: uuid.UUID) -> None:
    invoice = await _invoice(db, context.tenant.id, invoice_id)
    invoice.share_token_hash = None
    invoice.share_version += 1
    await db.commit()


async def public_invoice(db: AsyncSession, token: str) -> PublicInvoiceOut:
    found = (await db.execute(_LOOKUP, {"h": _hash(token)})).first()
    if found is None:
        raise NotFoundError(LINK_NOT_FOUND)
    tenant_id, invoice_id = found
    await set_tenant_context(db, tenant_id)
    sale = await service.get_sale(db, tenant_id, invoice_id)
    shop_name = await db.scalar(select(Tenant.name).where(Tenant.id == tenant_id))
    return PublicInvoiceOut(
        shop_name=shop_name or "",
        number=sale.number,
        created_at=sale.created_at,
        lines=[
            PublicLineOut(
                name_ar=item.name_ar,
                unit_name_ar=item.unit_name_ar,
                quantity=item.quantity,
                unit_price=item.unit_price,
                line_total=item.line_total,
            )
            for item in sale.lines
        ],
        subtotal=sale.subtotal,
        discount=sale.discount,
        total=sale.total,
        paid=sale.paid,
        remaining=sale.credit,
        returned_total=sale.returned_total,
    )
