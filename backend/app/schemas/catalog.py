"""Schemas do catálogo e da comparação de preços."""
from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------- #
# Categorias
# --------------------------------------------------------------------------- #
class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(min_length=1, max_length=120)


class CategoryPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    slug: str


# --------------------------------------------------------------------------- #
# Lojas
# --------------------------------------------------------------------------- #
class StoreCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    slug: str = Field(min_length=1, max_length=160)
    latitude: float | None = None
    longitude: float | None = None
    pix_key: str | None = Field(default=None, max_length=140)


class StorePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    slug: str
    is_active: bool
    pix_key: str | None = None


# --------------------------------------------------------------------------- #
# Produtos (catálogo universal)
# --------------------------------------------------------------------------- #
class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    brand: str | None = Field(default=None, max_length=120)
    ean: str | None = Field(default=None, max_length=14)
    image_url: str | None = Field(default=None, max_length=500)
    category_id: uuid.UUID | None = None
    package_size: float = Field(gt=0)
    package_unit: str = Field(description="g, kg, ml, l ou un")


class ProductBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    brand: str | None
    image_url: str | None
    package_size: float
    package_unit: str
    base_unit: str


# --------------------------------------------------------------------------- #
# Ofertas e comparação
# --------------------------------------------------------------------------- #
class OfferUpsert(BaseModel):
    price: float = Field(gt=0)
    original_price: float | None = Field(default=None, gt=0)
    in_stock: bool = True
    stock_quantity: int | None = Field(default=None, ge=0)


class StoreOffer(BaseModel):
    """Uma oferta com o preço unitário normalizado já calculado (RN-001)."""
    store_id: uuid.UUID
    store_name: str
    price: float
    original_price: float | None
    in_stock: bool
    unit_price: float
    unit_label: str  # ex.: "R$/l"
    is_best: bool = False


class ProductWithBestPrice(ProductBase):
    best_unit_price: float | None = None
    unit_label: str | None = None
    store_count: int = 0


class ProductComparison(ProductBase):
    """Detalhe do produto (PDP) com a comparação entre lojas, ordenada."""
    offers: list[StoreOffer]
    best_unit_price: float | None = None
    unit_label: str | None = None


class ProductList(BaseModel):
    items: list[ProductWithBestPrice]
    total: int
    page: int
    page_size: int
