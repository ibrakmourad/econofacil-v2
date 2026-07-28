"""Modelo de pagamento.

RN-022 — liquidação Pix por loja: um pedido split entre N lojas gera N
registros de pagamento aqui, um por loja, cada um com seu próprio valor
(o subtotal daquela loja), seu próprio txid/BR Code/QR — e, quando a loja
tem chave Pix própria configurada, na chave dela, não na da plataforma.
Um pedido de loja única continua gerando exatamente 1 pagamento, então o
comportamento anterior (uma cobrança por pedido) é só o caso N=1 deste
modelo mais geral.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PaymentMethod(str, enum.Enum):
    PIX = "pix"
    ECONOPAY = "econopay"
    CARD = "card"


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    PAID = "paid"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class Payment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("order_id", "store_id", name="uq_payment_order_store"),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # loja a que esta cobrança se refere — snapshot, mesmo padrão de
    # OrderItem/OrderFulfillment (o histórico não deve depender do catálogo).
    store_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    store_name: Mapped[str] = mapped_column(String(160), nullable=False)

    method: Mapped[PaymentMethod] = mapped_column(
        Enum(PaymentMethod, native_enum=False, length=12), nullable=False
    )
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, native_enum=False, length=12),
        default=PaymentStatus.PENDING,
        nullable=False,
    )
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)

    # específicos de Pix
    txid: Mapped[str | None] = mapped_column(String(35), unique=True, index=True, nullable=True)
    br_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    qr_svg: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
