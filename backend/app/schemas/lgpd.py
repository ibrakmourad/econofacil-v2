"""Schemas dos endpoints de LGPD (consentimento, exportação, exclusão)."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.consent import ConsentPurpose


class ConsentItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    purpose: ConsentPurpose
    granted: bool
    terms_version: str
    granted_at: datetime | None = None
    revoked_at: datetime | None = None


class ConsentUpdate(BaseModel):
    purpose: ConsentPurpose
    granted: bool


class ConsentUpdateBatch(BaseModel):
    consents: list[ConsentUpdate]


class DataExport(BaseModel):
    """Pacote de portabilidade de dados do titular."""
    user_id: uuid.UUID
    profile: dict
    consents: list[ConsentItem]
    sessions: list[dict]
    generated_at: datetime
