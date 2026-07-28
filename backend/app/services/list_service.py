"""Serviço de Listas de compras.

Diferente do carrinho (RN-008, expira em 24h), uma lista é permanente — serve
para compras recorrentes. Reaproveita a mesma lógica de precificação do
carrinho (``cart_service.price_line_items``) e o otimizador de cestas
(RN-018) para simular quanto custaria comprar a lista inteira, em loja única
ou dividida.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Product
from app.models.shopping_list import ShoppingList, ShoppingListItem
from app.models.user import User
from app.services import cart_service, optimizer_service


async def create_list(db: AsyncSession, user: User, name: str) -> ShoppingList:
    lst = ShoppingList(user_id=user.id, name=name)
    db.add(lst)
    await db.commit()
    await db.refresh(lst)
    return lst


async def list_my_lists(db: AsyncSession, user: User) -> list[ShoppingList]:
    result = await db.execute(
        select(ShoppingList)
        .where(ShoppingList.user_id == user.id)
        .order_by(ShoppingList.updated_at.desc())
    )
    return list(result.scalars().all())


async def get_owned_list(db: AsyncSession, user: User, list_id: uuid.UUID) -> ShoppingList | None:
    lst = await db.get(ShoppingList, list_id)
    if lst is None or lst.user_id != user.id:
        return None
    return lst


async def rename_list(db: AsyncSession, lst: ShoppingList, name: str) -> ShoppingList:
    lst.name = name
    await db.commit()
    await db.refresh(lst)
    return lst


async def delete_list(db: AsyncSession, lst: ShoppingList) -> None:
    await db.delete(lst)
    await db.commit()


async def add_item(db: AsyncSession, lst: ShoppingList, product_id: uuid.UUID, quantity: int) -> ShoppingList:
    if await db.get(Product, product_id) is None:
        raise ValueError("Produto não encontrado")
    existing = next((i for i in lst.items if i.product_id == product_id), None)
    if existing:
        existing.quantity += quantity
    else:
        db.add(ShoppingListItem(list_id=lst.id, product_id=product_id, quantity=quantity))
    await db.commit()
    await db.refresh(lst)
    return lst


async def set_item_quantity(
    db: AsyncSession, lst: ShoppingList, product_id: uuid.UUID, quantity: int
) -> ShoppingList:
    item = next((i for i in lst.items if i.product_id == product_id), None)
    if item is None:
        raise ValueError("Item não está na lista")
    if quantity <= 0:
        await db.delete(item)
    else:
        item.quantity = quantity
    await db.commit()
    await db.refresh(lst)
    return lst


async def remove_item(db: AsyncSession, lst: ShoppingList, product_id: uuid.UUID) -> ShoppingList:
    item = next((i for i in lst.items if i.product_id == product_id), None)
    if item is not None:
        await db.delete(item)
        await db.commit()
        await db.refresh(lst)
    return lst


async def build_view(db: AsyncSession, lst: ShoppingList) -> dict:
    """Monta a visão da lista com melhor preço estimado por item."""
    lines = [(i.product_id, i.quantity) for i in lst.items]
    items, subtotal, qty_total = await cart_service.price_line_items(db, lines)
    return {
        "id": lst.id, "name": lst.name, "item_count": qty_total,
        "subtotal_estimate": subtotal, "items": items,
        "created_at": lst.created_at, "updated_at": lst.updated_at,
    }


async def compare(db: AsyncSession, lst: ShoppingList) -> dict:
    """Reaproveita o otimizador do carrinho (RN-018) para comparar loja única
    × split para a lista inteira, sem depender do carrinho ativo do usuário.
    """
    products = {
        p.id: p
        for p in (
            await db.execute(
                select(Product).where(Product.id.in_([i.product_id for i in lst.items]))
            )
        ).scalars().all()
    }
    offers = await cart_service.gather_offers(db, list(products.keys()))
    items = [
        {"product_id": i.product_id, "name": products[i.product_id].name, "quantity": i.quantity}
        for i in lst.items if i.product_id in products
    ]
    plan = optimizer_service.plan_purchase(items, offers)

    unavailable = []
    for i in lst.items:
        prod = products.get(i.product_id)
        if prod is not None and not offers.get(i.product_id):
            unavailable.append({
                "product_id": prod.id,
                "product_name": prod.name,
                "suggestions": await cart_service.suggest_substitutes(db, prod),
            })
    plan["unavailable_items"] = unavailable
    return plan


async def add_to_cart(db: AsyncSession, user: User, lst: ShoppingList) -> dict:
    """Copia os itens da lista para o carrinho ativo do usuário, somando
    quantidades a itens já presentes (mesmo comportamento de ``add_item``).
    """
    cart = await cart_service.get_active_cart(db, user)
    added = skipped = 0
    for item in lst.items:
        product = await db.get(Product, item.product_id)
        if product is None:
            skipped += 1
            continue
        cart = await cart_service.add_item(db, cart, item.product_id, item.quantity)
        added += 1
    return {"added": added, "skipped_unavailable": skipped}
