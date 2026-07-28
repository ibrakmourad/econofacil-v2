"""Schemas de recomendações da Noor V2 (RN-023)."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class RelatedProduct(BaseModel):
    product_id: uuid.UUID
    name: str
    co_purchase_count: int
    best_price: float
    store_count: int


class ReorderSuggestion(BaseModel):
    product_id: uuid.UUID
    name: str
    times_bought: int
    last_bought_at: datetime
    best_price: float
    store_count: int
