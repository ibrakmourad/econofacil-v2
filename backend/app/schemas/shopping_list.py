"""Schemas de Listas de compras."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ListCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ListRename(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class AddListItemRequest(BaseModel):
    product_id: uuid.UUID
    quantity: int = Field(default=1, ge=1)


class SetListItemQuantityRequest(BaseModel):
    quantity: int = Field(ge=0)


class ListItemView(BaseModel):
    product_id: uuid.UUID
    name: str
    brand: str | None = None
    image_url: str | None = None
    package_size: float
    package_unit: str
    quantity: int
    best_price: float | None = None
    available: bool


class ListSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    item_count: int
    created_at: datetime
    updated_at: datetime


class ListView(BaseModel):
    id: uuid.UUID
    name: str
    item_count: int
    subtotal_estimate: float
    items: list[ListItemView]
    created_at: datetime
    updated_at: datetime


class AddToCartResult(BaseModel):
    added: int
    skipped_unavailable: int
