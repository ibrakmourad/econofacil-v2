"""Modelo de promoção (gestão de promoções do comerciante).

Uma promoção rebaixa temporariamente o preço de uma oferta. Ao ativar, o preço
anterior é guardado em ``original_price`` da oferta (que o front exibe riscado)
e restaurado quando a promoção termina. A expiração automática por agendador é
prevista para produção; aqui ela é aplicada de forma oportunista nas leituras.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PromotionStatus(str, enum.Enum):
    ACTIVE = "active"
    ENDED = "ended"


class Promotion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "promotions"

    store_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), index=True, nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    promo_price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    base_price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[PromotionStatus] = mapped_column(
        Enum(PromotionStatus, native_enum=False, length=10),
        default=PromotionStatus.ACTIVE,
        nullable=False,
    )
