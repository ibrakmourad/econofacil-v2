"""Modelo de consentimento granular (LGPD)."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ConsentPurpose(str, enum.Enum):
    """Finalidades de tratamento de dados."""
    DATA_PROCESSING = "data_processing"   # essencial para operar a conta
    MARKETING = "marketing"               # comunicações promocionais
    ANALYTICS = "analytics"               # métricas de uso
    PERSONALIZATION = "personalization"   # recomendações da IA Noor


class Consent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "consents"
    __table_args__ = (
        UniqueConstraint("user_id", "purpose", name="uq_consent_user_purpose"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    purpose: Mapped[ConsentPurpose] = mapped_column(
        Enum(ConsentPurpose, native_enum=False, length=30), nullable=False
    )
    granted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    terms_version: Mapped[str] = mapped_column(String(20), nullable=False)
    granted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
