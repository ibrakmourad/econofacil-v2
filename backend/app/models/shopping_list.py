"""Modelos de Listas de compras (módulo de backend da tela "Listas").

Diferente do carrinho (``Cart``, RN-008), que expira em 24h e serve para a
compra em andamento, uma lista é permanente — pensada para compras
recorrentes (ex.: "Feira da semana", "Churrasco de sábado"). O usuário pode
comparar o custo da lista inteira (mesmo cálculo de loja única × split do
carrinho, RN-018) e/ou copiá-la para o carrinho quando for às compras.
"""
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ShoppingList(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "shopping_lists"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)

    items: Mapped[list["ShoppingListItem"]] = relationship(
        back_populates="shopping_list", cascade="all, delete-orphan", lazy="selectin"
    )


class ShoppingListItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "shopping_list_items"
    __table_args__ = (
        UniqueConstraint("list_id", "product_id", name="uq_list_product"),
    )

    list_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shopping_lists.id", ondelete="CASCADE"), index=True, nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    shopping_list: Mapped[ShoppingList] = relationship(back_populates="items")
