"""Endpoints do Portal do Comerciante (/merchant)."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, require_role
from app.models.user import UserRole
from app.schemas.catalog import StorePublic
from app.schemas.merchant import (
    InventoryRow,
    MerchantOrder,
    OrderStatusUpdate,
    PromotionCreate,
    PromotionView,
    StoreReport,
)
from app.services import merchant_service
from app.services.audit_service import log_action
from app.services.merchant_service import AmbiguousStore, NotOwner, StoreNotFound

router = APIRouter(prefix="/merchant", tags=["merchant"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
Merchant = Annotated[object, Depends(require_role(UserRole.MERCHANT, UserRole.ADMIN))]


async def _owned(db, user, store_id):
    try:
        return await merchant_service.get_owned_store(db, user, store_id)
    except StoreNotFound:
        raise HTTPException(status_code=404, detail="Loja não encontrada")
    except NotOwner:
        raise HTTPException(status_code=403, detail="Loja não pertence a você")


# --------------------------------------------------------------------------- #
# Lojas
# --------------------------------------------------------------------------- #
@router.get("/stores", response_model=list[StorePublic])
async def my_stores(db: DbSession, user: CurrentUser, _: Merchant):
    return await merchant_service.list_my_stores(db, user)


# --------------------------------------------------------------------------- #
# Inventário (catálogo / estoque / preços)
# --------------------------------------------------------------------------- #
@router.get("/stores/{store_id}/inventory", response_model=list[InventoryRow])
async def inventory(store_id: uuid.UUID, db: DbSession, user: CurrentUser, _: Merchant):
    await _owned(db, user, store_id)
    return await merchant_service.list_inventory(db, store_id)


# --------------------------------------------------------------------------- #
# Promoções
# --------------------------------------------------------------------------- #
@router.get("/stores/{store_id}/promotions", response_model=list[PromotionView])
async def list_promotions(store_id: uuid.UUID, db: DbSession, user: CurrentUser, _: Merchant):
    await _owned(db, user, store_id)
    return await merchant_service.list_promotions(db, store_id)


@router.post("/stores/{store_id}/promotions", response_model=PromotionView, status_code=status.HTTP_201_CREATED)
async def create_promotion(
    store_id: uuid.UUID, payload: PromotionCreate, db: DbSession, user: CurrentUser, _: Merchant
):
    await _owned(db, user, store_id)
    try:
        promo = await merchant_service.create_promotion(
            db, store_id, payload.product_id, payload.promo_price, payload.ends_at
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    await log_action(db, action="merchant.promotion_created", user_id=user.id, entity=str(promo.id))
    return promo


@router.delete("/promotions/{promo_id}", response_model=PromotionView)
async def end_promotion(promo_id: uuid.UUID, db: DbSession, user: CurrentUser, _: Merchant):
    try:
        promo = await merchant_service.end_promotion(db, user, promo_id)
    except StoreNotFound:
        raise HTTPException(status_code=404, detail="Promoção não encontrada")
    except NotOwner:
        raise HTTPException(status_code=403, detail="Promoção não pertence a você")
    return promo


# --------------------------------------------------------------------------- #
# Pedidos do comerciante
# --------------------------------------------------------------------------- #
@router.get("/orders", response_model=list[MerchantOrder])
async def merchant_orders(db: DbSession, user: CurrentUser, _: Merchant):
    store_ids = await merchant_service.my_store_ids(db, user)
    return await merchant_service.list_orders(db, store_ids)


@router.patch("/orders/{order_id}/status", response_model=MerchantOrder)
async def update_order_status(
    order_id: uuid.UUID, payload: OrderStatusUpdate, db: DbSession, user: CurrentUser, _: Merchant
):
    store_ids = await merchant_service.my_store_ids(db, user)
    try:
        row = await merchant_service.update_order_status(
            db, store_ids, order_id, payload.status, store_id=payload.store_id
        )
    except StoreNotFound:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    except NotOwner:
        raise HTTPException(status_code=403, detail="Pedido não inclui suas lojas")
    except AmbiguousStore:
        raise HTTPException(
            status_code=422,
            detail="Você possui mais de uma loja neste pedido; informe store_id",
        )
    await log_action(
        db, action="merchant.order_status_updated", user_id=user.id,
        entity=str(order_id), details={"store_id": str(row["store_id"]), "status": payload.status.value},
    )
    return row


# --------------------------------------------------------------------------- #
# Relatório operacional
# --------------------------------------------------------------------------- #
@router.get("/stores/{store_id}/report", response_model=StoreReport)
async def store_report(store_id: uuid.UUID, db: DbSession, user: CurrentUser, _: Merchant):
    await _owned(db, user, store_id)
    return await merchant_service.store_report(db, store_id)
