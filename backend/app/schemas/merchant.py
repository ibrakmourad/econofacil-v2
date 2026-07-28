"""Schemas do Portal do Comerciante."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.order import OrderStatus
from app.models.promotion import PromotionStatus


# --------------------------------------------------------------------------- #
# Inventário
# --------------------------------------------------------------------------- #
class InventoryRow(BaseModel):
    product_id: uuid.UUID
    product_name: str
    package_size: float
    package_unit: str
    price: float
    original_price: float | None = None
    in_stock: bool
    stock_quantity: int | None = None


# --------------------------------------------------------------------------- #
# Promoções
# --------------------------------------------------------------------------- #
class PromotionCreate(BaseModel):
    product_id: uuid.UUID
    promo_price: float = Field(gt=0)
    ends_at: datetime


class PromotionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    store_id: uuid.UUID
    product_id: uuid.UUID
    promo_price: float
    base_price: float
    ends_at: datetime
    status: PromotionStatus


# --------------------------------------------------------------------------- #
# Pedidos do comerciante
# --------------------------------------------------------------------------- #
class MerchantOrderLine(BaseModel):
    product_name: str
    quantity: int
    unit_price: float
    line_total: float


class MerchantOrder(BaseModel):
    order_id: uuid.UUID
    code: str
    store_id: uuid.UUID
    store_name: str
    status: OrderStatus
    created_at: datetime
    store_subtotal: float
    items: list[MerchantOrderLine]


class OrderStatusUpdate(BaseModel):
    status: OrderStatus
    # obrigatório apenas quando o comerciante possui mais de uma loja no
    # mesmo pedido (split); se ele só tem uma, é inferido automaticamente.
    store_id: uuid.UUID | None = None


# --------------------------------------------------------------------------- #
# Relatório
# --------------------------------------------------------------------------- #
class TopProduct(BaseModel):
    product_name: str
    quantity: int
    revenue: float


class StoreReport(BaseModel):
    orders_count: int
    revenue: float
    units_sold: int
    top_products: list[TopProduct]
