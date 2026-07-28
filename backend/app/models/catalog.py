"""Modelos do catálogo universal e ofertas por loja.

Estrutura:
- ``Category``     : categorias do catálogo (Hortifruti, Mercearia...).
- ``Store``        : loja/comerciante onde os produtos são vendidos.
- ``Product``      : item canônico do catálogo universal (independe de loja).
- ``StoreProduct`` : oferta = preço/estoque de um produto numa loja.

A comparação de preços (RN-001) usa ``Product.base_size`` para derivar o
preço unitário normalizado: ``StoreProduct.price / Product.base_size``.
"""
from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Category(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "categories"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)


class Store(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "stores"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(160), unique=True, index=True, nullable=False)
    # comerciante dono da loja (opcional nesta fase)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # localização para "perto de você" (uso futuro pela Noor)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # RN-022: chave Pix própria do comerciante para liquidação por loja. Se
    # não configurada, a cobrança dessa loja cai na chave da plataforma
    # (que age como intermediária) — ver app/services/payment_service.py.
    pix_key: Mapped[str | None] = mapped_column(String(140), nullable=True)


class Product(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "products"

    name: Mapped[str] = mapped_column(String(200), index=True, nullable=False)
    brand: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ean: Mapped[str | None] = mapped_column(String(14), index=True, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), index=True, nullable=True
    )

    # embalagem exibida (ex.: 1 + "L")
    package_size: Mapped[float] = mapped_column(Float, nullable=False)
    package_unit: Mapped[str] = mapped_column(String(20), nullable=False)

    # normalização para comparação (RN-001)
    unit_type: Mapped[str] = mapped_column(String(10), nullable=False)   # weight|volume|count
    base_unit: Mapped[str] = mapped_column(String(5), nullable=False)    # kg|l|un
    base_size: Mapped[float] = mapped_column(Float, nullable=False)      # tamanho na unidade base

    category: Mapped[Category | None] = relationship(lazy="joined")


class StoreProduct(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "store_products"
    __table_args__ = (
        UniqueConstraint("store_id", "product_id", name="uq_offer_store_product"),
    )

    store_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), index=True, nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True, nullable=False
    )
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    original_price: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    in_stock: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    stock_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)

    store: Mapped[Store] = relationship(lazy="joined")
    product: Mapped[Product] = relationship(lazy="joined")
