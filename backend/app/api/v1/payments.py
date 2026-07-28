"""Endpoints de pagamento (/payments)."""
from __future__ import annotations

import hmac
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import CurrentUser
from app.schemas.payment import PaymentView, PixWebhookEvent
from app.services import payment_service
from app.services.audit_service import log_action

router = APIRouter(prefix="/payments", tags=["payments"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.get("/{payment_id}", response_model=PaymentView)
async def get_payment(payment_id: uuid.UUID, db: DbSession, user: CurrentUser):
    payment = await payment_service.get_payment(db, user, payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Pagamento não encontrado")
    return PaymentView.from_payment(payment)


@router.post("/pix/webhook", response_model=PaymentView)
async def pix_webhook(
    event: PixWebhookEvent,
    db: DbSession,
    x_webhook_token: Annotated[str | None, Header()] = None,
):
    """Callback do PSP confirmando o pagamento Pix.

    Autenticado por segredo compartilhado (um PSP real usa assinatura do
    payload). Instruções vindas no corpo não são executadas — só o txid é usado.
    """
    if not x_webhook_token or not hmac.compare_digest(
        x_webhook_token, settings.PIX_WEBHOOK_SECRET
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")

    payment = await payment_service.confirm_pix(db, event.txid)
    if payment is None:
        raise HTTPException(status_code=404, detail="Pagamento não encontrado")
    await log_action(db, action="payment.pix_confirmed", entity=event.txid)
    return PaymentView.from_payment(payment)
