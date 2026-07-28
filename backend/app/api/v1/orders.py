"""Endpoints de pedidos (/orders)."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser
from app.schemas.cart import OrderSummary, OrderView
from app.services import cart_service

router = APIRouter(prefix="/orders", tags=["orders"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.get("", response_model=list[OrderSummary])
async def list_orders(db: DbSession, user: CurrentUser):
    return await cart_service.list_orders(db, user)


@router.get("/{order_id}", response_model=OrderView)
async def get_order(order_id: uuid.UUID, db: DbSession, user: CurrentUser):
    order = await cart_service.get_order(db, user, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    from app.schemas.payment import PaymentView
    from app.services import payment_service

    view = OrderView.model_validate(order)
    payments = await payment_service.list_for_order(db, order.id)
    view.payments = [PaymentView.from_payment(p) for p in payments]
    return view
