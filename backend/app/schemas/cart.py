"""Schemas de carrinho, otimização e pedidos."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.order import OrderStatus
from app.schemas.payment import PaymentView


# --------------------------------------------------------------------------- #
# Carrinho
# --------------------------------------------------------------------------- #
class AddItemRequest(BaseModel):
    product_id: uuid.UUID
    quantity: int = Field(default=1, ge=1)


class SetQuantityRequest(BaseModel):
    quantity: int = Field(ge=0)


class CartItemView(BaseModel):
    product_id: uuid.UUID
    name: str
    brand: str | None = None
    image_url: str | None = None
    package_size: float
    package_unit: str
    quantity: int
    best_price: float | None = None
    available: bool


class CartView(BaseModel):
    id: uuid.UUID
    expires_at: datetime
    item_count: int
    subtotal_estimate: float
    items: list[CartItemView]


# --------------------------------------------------------------------------- #
# Otimização (RN-018)
# --------------------------------------------------------------------------- #
class PlanLine(BaseModel):
    product_id: uuid.UUID
    product_name: str
    quantity: int
    unit_price: float
    line_total: float


class StorePlan(BaseModel):
    store_id: uuid.UUID
    store_name: str
    subtotal: float
    items: list[PlanLine]


class PurchaseOption(BaseModel):
    stores: list[StorePlan]
    total: float
    store_count: int


class SubstituteOption(BaseModel):
    product_id: uuid.UUID
    name: str
    price: float


class UnavailableItem(BaseModel):
    product_id: uuid.UUID
    product_name: str
    suggestions: list[SubstituteOption]


class OptimizeResult(BaseModel):
    fulfillable: bool
    recommended: str | None
    savings: float
    savings_pct: float
    meets_min_savings: bool
    single_store: PurchaseOption | None = None
    split: PurchaseOption | None = None
    unavailable_items: list[UnavailableItem] = []
    engine: dict | None = None


# --------------------------------------------------------------------------- #
# Checkout / Pedidos
# --------------------------------------------------------------------------- #
class CheckoutRequest(BaseModel):
    strategy: str = Field(default="recommended", pattern="^(recommended|single|split)$")
    payment_method: str = Field(default="pix", pattern="^(pix|econopay|card)$")


class OrderItemView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    store_id: uuid.UUID
    store_name: str
    product_id: uuid.UUID
    product_name: str
    quantity: int
    unit_price: float
    line_total: float


class OrderFulfillmentView(BaseModel):
    """Status de atendimento de uma loja dentro do pedido (RN-019)."""
    model_config = ConfigDict(from_attributes=True)
    store_id: uuid.UUID
    store_name: str
    status: OrderStatus


class OrderView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    code: str
    status: OrderStatus
    subtotal: float
    savings: float
    total: float
    store_count: int
    created_at: datetime
    items: list[OrderItemView]
    fulfillments: list[OrderFulfillmentView] = []
    payments: list[PaymentView] = []


class OrderSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    code: str
    status: OrderStatus
    total: float
    savings: float
    store_count: int
    created_at: datetime
