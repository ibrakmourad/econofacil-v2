"""Endpoints de LGPD (/lgpd): consentimento, exportação e exclusão."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser
from app.schemas.auth import MessageResponse
from app.schemas.lgpd import (
    ConsentItem,
    ConsentUpdateBatch,
    DataExport,
)
from app.services import lgpd_service
from app.services.audit_service import log_action

router = APIRouter(prefix="/lgpd", tags=["lgpd"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.get("/consents", response_model=list[ConsentItem])
async def list_consents(db: DbSession, user: CurrentUser):
    return await lgpd_service.get_consents(db, user.id)


@router.put("/consents", response_model=list[ConsentItem])
async def update_consents(
    payload: ConsentUpdateBatch, db: DbSession, user: CurrentUser
):
    for item in payload.consents:
        await lgpd_service.set_consent(
            db, user.id, item.purpose, item.granted, commit=False
        )
    await db.commit()
    await log_action(
        db,
        action="lgpd.consent_updated",
        user_id=user.id,
        details={c.purpose.value: c.granted for c in payload.consents},
    )
    return await lgpd_service.get_consents(db, user.id)


@router.get("/export", response_model=DataExport)
async def export_data(db: DbSession, user: CurrentUser):
    """Portabilidade de dados (Art. 18, LGPD)."""
    data = await lgpd_service.export_user_data(db, user)
    await log_action(db, action="lgpd.data_exported", user_id=user.id)
    return data


@router.delete("/account", status_code=status.HTTP_200_OK, response_model=MessageResponse)
async def delete_account(db: DbSession, user: CurrentUser):
    """Direito ao esquecimento: anonimiza os dados pessoais do titular."""
    await log_action(db, action="lgpd.account_deleted", user_id=user.id)
    await lgpd_service.anonymize_user(db, user)
    return MessageResponse(message="Conta anonimizada conforme solicitado")
