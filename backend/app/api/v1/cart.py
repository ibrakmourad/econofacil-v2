"""Endpoints de carrinho (/cart)."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser
from app.schemas.cart import (
    AddItemRequest,
    CartView,
    CheckoutRequest,
    OptimizeResult,
    OrderView,
    SetQuantityRequest,
)
from app.services import cart_service
from app.services.audit_service import log_action

router = APIRouter(prefix="/cart", tags=["cart"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def _build_view(db: AsyncSession, cart) -> CartView:
    return CartView(**await cart_service.build_view(db, cart))


@router.get("", response_model=CartView)
async def get_cart(db: DbSession, user: CurrentUser):
    cart = await cart_service.get_active_cart(db, user)
    return await _build_view(db, cart)


@router.post("/items", response_model=CartView)
async def add_item(payload: AddItemRequest, db: DbSession, user: CurrentUser):
    cart = await cart_service.get_active_cart(db, user)
    try:
        cart = await cart_service.add_item(db, cart, payload.product_id, payload.quantity)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return await _build_view(db, cart)


@router.patch("/items/{product_id}", response_model=CartView)
async def set_quantity(product_id: uuid.UUID, payload: SetQuantityRequest, db: DbSession, user: CurrentUser):
    cart = await cart_service.get_active_cart(db, user)
    try:
        cart = await cart_service.set_item_quantity(db, cart, product_id, payload.quantity)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return await _build_view(db, cart)


@router.delete("/items/{product_id}", response_model=CartView)
async def remove_item(product_id: uuid.UUID, db: DbSession, user: CurrentUser):
    cart = await cart_service.get_active_cart(db, user)
    cart = await cart_service.remove_item(db, cart, product_id)
    return await _build_view(db, cart)


@router.delete("", response_model=CartView)
async def clear_cart(db: DbSession, user: CurrentUser):
    cart = await cart_service.get_active_cart(db, user)
    cart = await cart_service.clear(db, cart)
    return await _build_view(db, cart)


@router.get("/optimize", response_model=OptimizeResult)
async def optimize_cart(db: DbSession, user: CurrentUser):
    cart = await cart_service.get_active_cart(db, user)
    plan = await cart_service.optimize(db, cart)
    return OptimizeResult(**plan)


@router.post("/checkout", response_model=OrderView)
async def checkout(payload: CheckoutRequest, db: DbSession, user: CurrentUser):
    cart = await cart_service.get_active_cart(db, user)
    try:
        order = await cart_service.checkout(db, user, cart, payload.strategy)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    from app.models.payment import PaymentMethod
    from app.schemas.payment import PaymentView
    from app.services import payment_service

    try:
        payments = await payment_service.create_for_order(
            db, order, PaymentMethod(payload.payment_method)
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    await log_action(db, action="cart.checkout", user_id=user.id, entity=order.code,
                     details={"strategy": payload.strategy, "savings": float(order.savings),
                              "payment_method": payload.payment_method})
    view = OrderView.model_validate(order)
    view.payments = [PaymentView.from_payment(p) for p in payments]
    return view
