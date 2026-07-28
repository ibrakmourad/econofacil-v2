"""Endpoints da Noor (/noor) — Noor Monitor (motor de otimização) e Noor V2
(recomendações contextuais, RN-023)."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import CurrentUser
from app.noor import solver as noor_solver
from app.schemas.noor import RelatedProduct, ReorderSuggestion
from app.services import optimizer_service, recommendation_service

router = APIRouter(prefix="/noor", tags=["noor"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.get("/status")
async def noor_status():
    available = noor_solver.solver_available()
    if settings.NOOR_FORCE_HEURISTIC:
        engine = "heuristic"
    elif settings.NOOR_SOLVER_ENABLED and available:
        engine = "noor-ilp"
    else:
        engine = "heuristic"
    return {
        "version": noor_solver.NOOR_SOLVER_VERSION,
        "engine": engine,
        "solver_available": available,
        "solver_enabled": settings.NOOR_SOLVER_ENABLED,
        "min_split_savings": optimizer_service.MIN_SPLIT_SAVINGS,
        "max_stores": optimizer_service.MAX_STORES,
        "metrics": optimizer_service.get_metrics(),
        "recommender_version": recommendation_service.NOOR_RECOMMENDER_VERSION,
    }


# --------------------------------------------------------------------------- #
# Noor V2 — recomendações contextuais (RN-023)
# --------------------------------------------------------------------------- #
@router.get("/recommendations/related/{product_id}", response_model=list[RelatedProduct])
async def related_products(
    product_id: uuid.UUID,
    db: DbSession,
    limit: int = Query(default=5, ge=1, le=20),
):
    """"Quem comprou X também comprou" — leitura pública, como o catálogo."""
    return await recommendation_service.related_products(db, product_id, limit=limit)


@router.get("/recommendations/reorder", response_model=list[ReorderSuggestion])
async def reorder_suggestions(
    db: DbSession,
    user: CurrentUser,
    limit: int = Query(default=5, ge=1, le=20),
):
    """"Você costuma comprar" — pessoal, baseado no histórico do usuário logado."""
    return await recommendation_service.reorder_suggestions(db, user, limit=limit)
