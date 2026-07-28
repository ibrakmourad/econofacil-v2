"""Serviço de recomendações da Noor V2 (RN-023).

Duas recomendações calculadas diretamente a partir do histórico real de
pedidos — sem depender de infraestrutura de ML pesada (treinamento,
serving, etc.), mas versionadas (``NOOR_RECOMMENDER_VERSION``) no mesmo
espírito do Noor Solver, para que uma futura Noor V3 baseada em modelo
treinado (com tracking/registry via MLflow, como previsto no roadmap do
Documento Mestre) possa substituir a implementação sem quebrar o contrato:

1. **"Quem comprou X também comprou"** (``related_products``) — coocorrência
   de produtos no mesmo pedido, por contagem simples de pedidos em que os
   dois produtos aparecem juntos.
2. **"Você costuma comprar"** (``reorder_suggestions``) — produtos que o
   próprio usuário comprou pelo menos duas vezes no histórico e que não
   estão no carrinho ativo agora.

Pedidos cancelados não contam como sinal de intenção de compra real e são
excluídos de ambos os cálculos.
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.cart import Cart, CartItem, CartStatus
from app.models.catalog import Product, Store, StoreProduct
from app.models.order import Order, OrderItem, OrderStatus
from app.models.user import User

NOOR_RECOMMENDER_VERSION = "noor-recommender-1.0.0"

# pedidos cancelados não contam como sinal de intenção de compra real
_EXCLUDED_STATUSES = (OrderStatus.CANCELLED,)


async def _best_price(db: AsyncSession, product_id: uuid.UUID) -> tuple[float | None, int]:
    """Melhor preço em estoque do produto e em quantas lojas ele está disponível."""
    result = await db.execute(
        select(func.min(StoreProduct.price), func.count(func.distinct(StoreProduct.store_id)))
        .join(Store, Store.id == StoreProduct.store_id)
        .where(
            StoreProduct.product_id == product_id,
            StoreProduct.in_stock.is_(True),
            Store.is_active.is_(True),
        )
    )
    price, store_count = result.one()
    return (float(price) if price is not None else None), int(store_count or 0)


async def related_products(
    db: AsyncSession, product_id: uuid.UUID, limit: int = 5
) -> list[dict]:
    """RN-023a: "quem comprou X também comprou" — coocorrência simples em
    pedidos não cancelados. Só recomenda produtos com oferta ativa."""
    oi1 = aliased(OrderItem)
    oi2 = aliased(OrderItem)

    result = await db.execute(
        select(oi2.product_id, func.count(func.distinct(oi2.order_id)).label("co_count"))
        .join(oi1, oi1.order_id == oi2.order_id)
        .join(Order, Order.id == oi2.order_id)
        .where(
            oi1.product_id == product_id,
            oi2.product_id != product_id,
            Order.status.notin_(_EXCLUDED_STATUSES),
        )
        .group_by(oi2.product_id)
        .order_by(func.count(func.distinct(oi2.order_id)).desc())
        .limit(limit * 3)  # folga: alguns candidatos podem não ter oferta ativa
    )

    out: list[dict] = []
    for pid, co_count in result.all():
        product = await db.get(Product, pid)
        if product is None:
            continue
        price, store_count = await _best_price(db, pid)
        if price is None:
            continue  # sem oferta ativa, não recomenda
        out.append({
            "product_id": pid,
            "name": product.name,
            "co_purchase_count": int(co_count),
            "best_price": price,
            "store_count": store_count,
        })
        if len(out) >= limit:
            break
    return out


async def reorder_suggestions(db: AsyncSession, user: User, limit: int = 5) -> list[dict]:
    """RN-023b: "você costuma comprar" — produtos com 2+ compras no
    histórico do próprio usuário, ausentes do carrinho ativo agora."""
    result = await db.execute(
        select(
            OrderItem.product_id,
            func.count(func.distinct(OrderItem.order_id)).label("times_bought"),
            func.max(Order.created_at).label("last_bought_at"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.user_id == user.id, Order.status.notin_(_EXCLUDED_STATUSES))
        .group_by(OrderItem.product_id)
        .having(func.count(func.distinct(OrderItem.order_id)) >= 2)
        .order_by(
            func.count(func.distinct(OrderItem.order_id)).desc(),
            func.max(Order.created_at).desc(),
        )
        .limit(limit * 3)
    )
    candidates = result.all()

    cart_result = await db.execute(
        select(CartItem.product_id)
        .join(Cart, Cart.id == CartItem.cart_id)
        .where(Cart.user_id == user.id, Cart.status == CartStatus.ACTIVE)
    )
    in_cart = {row[0] for row in cart_result.all()}

    out: list[dict] = []
    for pid, times_bought, last_bought_at in candidates:
        if pid in in_cart:
            continue
        product = await db.get(Product, pid)
        if product is None:
            continue
        price, store_count = await _best_price(db, pid)
        if price is None:
            continue
        out.append({
            "product_id": pid,
            "name": product.name,
            "times_bought": int(times_bought),
            "last_bought_at": last_bought_at,
            "best_price": price,
            "store_count": store_count,
        })
        if len(out) >= limit:
            break
    return out
