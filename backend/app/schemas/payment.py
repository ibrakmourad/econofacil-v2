"""Schemas de pagamento."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.payment import PaymentMethod, PaymentStatus


class PixDetails(BaseModel):
    txid: str
    br_code: str          # "copia e cola"
    qr_svg: str           # QR em SVG (string)
    expires_at: datetime


class PaymentView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    order_id: uuid.UUID
    store_id: uuid.UUID
    store_name: str
    method: PaymentMethod
    status: PaymentStatus
    amount: float
    pix: PixDetails | None = None

    @classmethod
    def from_payment(cls, p) -> "PaymentView":
        pix = None
        if p.method == PaymentMethod.PIX and p.br_code:
            pix = PixDetails(
                txid=p.txid, br_code=p.br_code, qr_svg=p.qr_svg, expires_at=p.expires_at
            )
        return cls(
            id=p.id, order_id=p.order_id, store_id=p.store_id, store_name=p.store_name,
            method=p.method, status=p.status, amount=float(p.amount), pix=pix,
        )


class PixWebhookEvent(BaseModel):
    txid: str
    event: str = "payment.confirmed"
