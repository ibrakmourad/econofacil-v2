"""Modelos de Receitas (módulo de backend da tela "Receitas").

Uma receita tem ingredientes; cada ingrediente pode, opcionalmente, estar
vinculado a um produto do catálogo universal (``product_id``). Isso é o que
permite gerar uma lista de compras ou adicionar diretamente ao carrinho a
partir da receita (ver ``app/services/recipe_service.py``). Ingredientes sem
vínculo (ex.: "sal a gosto") existem só como texto informativo — não entram
na conversão para compra.
"""
from __future__ import annotations

import uuid

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Recipe(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "recipes"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(160), unique=True, index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    servings: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    prep_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )

    ingredients: Mapped[list["RecipeIngredient"]] = relationship(
        back_populates="recipe",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="RecipeIngredient.position",
    )


class RecipeIngredient(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "recipe_ingredients"

    recipe_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recipes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # vínculo opcional com o catálogo universal — só ingredientes vinculados
    # entram na conversão receita -> carrinho/lista.
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    recipe: Mapped[Recipe] = relationship(back_populates="ingredients")
