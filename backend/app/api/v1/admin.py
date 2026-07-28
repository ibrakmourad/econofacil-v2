"""Endpoints administrativos (/admin).

Hoje só o disparo manual do job de expirações (RN-021) — útil para operar
sem esperar o próximo tick do agendador (ex.: demonstrações em plano free
que "dorme", ou para verificar o efeito imediatamente após configurar algo).
Em produção, o agendador de background já cobre isso automaticamente
(``app/core/scheduler.py``).
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import require_role
from app.models.user import UserRole
from app.schemas.admin import ExpirationsSummary
from app.services import expiration_service

router = APIRouter(prefix="/admin", tags=["admin"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
Admin = Annotated[object, Depends(require_role(UserRole.ADMIN))]


@router.post("/expirations/run", response_model=ExpirationsSummary)
async def run_expirations(db: DbSession, _: Admin):
    summary = await expiration_service.run_all(db)
    return ExpirationsSummary(**summary)
