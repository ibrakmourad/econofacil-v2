"""Serviço de carrinho: itens, expiração, ofertas, otimização e checkout."""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cart import Cart, CartItem, CartStatus
from app.models.catalog import Product, Store, StoreProduct
from app.models.order import Order, OrderItem
from app.models.user import User
from app.services import fulfillment_service, optimizer_service

CART_TTL = timedelta(hours=24)  # RN-008: usuário logado


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Carrinho ativo + itens
# --------------------------------------------------------------------------- #
async def get_active_cart(db: AsyncSession, user: User) -> Cart:
    result = await db.execute(
        select(Cart).where(Cart.user_id == user.id, Cart.status == CartStatus.ACTIVE)
    )
    cart = result.scalar_one_or_none()

    if cart and _aware(cart.expires_at) <= _utcnow():  # RN-008: expirou
        cart.status = CartStatus.EXPIRED
        await db.commit()
        cart = None

    if cart is None:
        cart = Cart(user_id=user.id, expires_at=_utcnow() + CART_TTL)
        db.add(cart)
        await db.commit()
        await db.refresh(cart)
    return cart


async def _touch(db: AsyncSession, cart: Cart) -> None:
    cart.expires_at = _utcnow() + CART_TTL
    await db.commit()


async def add_item(db: AsyncSession, cart: Cart, product_id: uuid.UUID, quantity: int) -> Cart:
    if await db.get(Product, product_id) is None:
        raise ValueError("Produto não encontrado")
    existing = next((i for i in cart.items if i.product_id == product_id), None)
    if existing:
        existing.quantity += quantity
    else:
        db.add(CartItem(cart_id=cart.id, product_id=product_id, quantity=quantity))
    await _touch(db, cart)
    await db.refresh(cart)
    return cart


async def set_item_quantity(db: AsyncSession, cart: Cart, product_id: uuid.UUID, quantity: int) -> Cart:
    item = next((i for i in cart.items if i.product_id == product_id), None)
    if item is None:
        raise ValueError("Item não está no carrinho")
    if quantity <= 0:
        await db.delete(item)
    else:
        item.quantity = quantity
    await _touch(db, cart)
    await db.refresh(cart)
    return cart


async def remove_item(db: AsyncSession, cart: Cart, product_id: uuid.UUID) -> Cart:
    item = next((i for i in cart.items if i.product_id == product_id), None)
    if item is not None:
        await db.delete(item)
        await _touch(db, cart)
        await db.refresh(cart)
    return cart


async def clear(db: AsyncSession, cart: Cart) -> Cart:
    for item in list(cart.items):
        await db.delete(item)
    await _touch(db, cart)
    await db.refresh(cart)
    return cart


# --------------------------------------------------------------------------- #
# Precificação de linhas (reutilizado pelo carrinho e pelas Listas)
# --------------------------------------------------------------------------- #
async def price_line_items(
    db: AsyncSession, lines: list[tuple[uuid.UUID, int]]
) -> tuple[list[dict], float, int]:
    """Recebe pares (product_id, quantidade) e devolve os itens precificados
    pelo melhor preço em estoque, o subtotal e a quantidade total.

    Usado tanto pelo carrinho (RN-008) quanto pelas Listas de compras, que
    compartilham a mesma lógica de "melhor preço disponível por produto".
    """
    pids = [pid for pid, _ in lines]
    products = {
        p.id: p
        for p in (await db.execute(select(Product).where(Product.id.in_(pids)))).scalars().all()
    } if pids else {}
    offers = await gather_offers(db, pids)

    items: list[dict] = []
    subtotal = 0.0
    qty_total = 0
    for pid, qty in lines:
        p = products.get(pid)
        if p is None:
            continue
        store_offers = offers.get(pid)
        best = min((o["price"] for o in store_offers.values()), default=None) if store_offers else None
        if best is not None:
            subtotal += best * qty
        qty_total += qty
        items.append({
            "product_id": p.id, "name": p.name, "brand": p.brand, "image_url": p.image_url,
            "package_size": p.package_size, "package_unit": p.package_unit,
            "quantity": qty, "best_price": best, "available": best is not None,
        })
    return items, round(subtotal, 2), qty_total


async def build_view(db: AsyncSession, cart: Cart) -> dict:
    """Monta a visão do carrinho (itens precificados + subtotal estimado)."""
    lines = [(i.product_id, i.quantity) for i in cart.items]
    items, subtotal, qty_total = await price_line_items(db, lines)
    return {
        "id": cart.id, "expires_at": cart.expires_at,
        "item_count": qty_total, "subtotal_estimate": subtotal, "items": items,
    }


# --------------------------------------------------------------------------- #
# Ofertas e substitutos
# --------------------------------------------------------------------------- #
async def gather_offers(db: AsyncSession, product_ids: list[uuid.UUID]) -> dict:
    """{product_id: {store_id: {"store_name", "price"}}} para itens em estoque."""
    if not product_ids:
        return {}
    result = await db.execute(
        select(StoreProduct)
        .join(Store, Store.id == StoreProduct.store_id)
        .where(
            StoreProduct.product_id.in_(product_ids),
            StoreProduct.in_stock.is_(True),
            Store.is_active.is_(True),
        )
    )
    offers: dict = {}
    for sp in result.scalars().all():
        offers.setdefault(sp.product_id, {})[sp.store_id] = {
            "store_name": sp.store.name,
            "price": float(sp.price),
        }
    return offers


async def suggest_substitutes(db: AsyncSession, product: Product, limit: int = 2) -> list[dict]:
    """RN-009: substitutos da mesma categoria, com estoque, mais baratos primeiro."""
    if product.category_id is None:
        return []
    min_price = func.min(StoreProduct.price).label("min_price")
    result = await db.execute(
        select(Product, min_price)
        .join(StoreProduct, StoreProduct.product_id == Product.id)
        .where(
            Product.category_id == product.category_id,
            Product.id != product.id,
            StoreProduct.in_stock.is_(True),
        )
        .group_by(Product.id)
        .order_by(min_price)
        .limit(limit)
    )
    return [
        {"product_id": p.id, "name": p.name, "price": float(mp)}
        for p, mp in result.all()
    ]


# --------------------------------------------------------------------------- #
# Otimização (RN-018)
# --------------------------------------------------------------------------- #
async def optimize(db: AsyncSession, cart: Cart) -> dict:
    products = {
        p.id: p
        for p in (
            await db.execute(
                select(Product).where(
                    Product.id.in_([i.product_id for i in cart.items])
                )
            )
        ).scalars().all()
    }
    offers = await gather_offers(db, list(products.keys()))

    items = [
        {"product_id": i.product_id, "name": products[i.product_id].name, "quantity": i.quantity}
        for i in cart.items
        if i.product_id in products
    ]
    plan = optimizer_service.plan_purchase(items, offers)

    # itens indisponíveis + substitutos (RN-009)
    unavailable = []
    for i in cart.items:
        prod = products.get(i.product_id)
        if prod is not None and not offers.get(i.product_id):
            unavailable.append({
                "product_id": prod.id,
                "product_name": prod.name,
                "suggestions": await suggest_substitutes(db, prod),
            })
    plan["unavailable_items"] = unavailable
    return plan


# --------------------------------------------------------------------------- #
# Checkout
# --------------------------------------------------------------------------- #
def _gen_code() -> str:
    return "EF-" + secrets.token_hex(3).upper()


async def checkout(db: AsyncSession, user: User, cart: Cart, strategy: str) -> Order:
    if not cart.items:
        raise ValueError("Carrinho vazio")

    plan = await optimize(db, cart)
    if not plan["fulfillable"]:
        raise ValueError("Carrinho não pode ser atendido em até 3 lojas")

    chosen = strategy
    if strategy == "recommended":
        chosen = plan["recommended"]

    if chosen == "split":
        option = plan["split"] or plan["single_store"]
    else:
        option = plan["single_store"] or plan["split"]
    if option is None:
        raise ValueError("Estratégia indisponível para este carrinho")

    # economia só é registrada quando o split é escolhido e há base de loja única
    savings = 0.0
    if chosen == "split" and plan["single_store"]:
        savings = round(plan["single_store"]["total"] - option["total"], 2)

    order = Order(
        user_id=user.id,
        code=_gen_code(),
        subtotal=option["total"],
        savings=savings,
        total=option["total"],
        store_count=option["store_count"],
    )
    db.add(order)
    await db.flush()

    for store in option["stores"]:
        for line in store["items"]:
            db.add(OrderItem(
                order_id=order.id,
                store_id=store["store_id"],
                store_name=store["store_name"],
                product_id=line["product_id"],
                product_name=line["product_name"],
                quantity=line["quantity"],
                unit_price=line["unit_price"],
                line_total=line["line_total"],
            ))

    await fulfillment_service.create_fulfillments(db, order, option["stores"])

    cart.status = CartStatus.CHECKED_OUT
    await db.commit()
    await db.refresh(order)
    return order


# --------------------------------------------------------------------------- #
# Pedidos
# --------------------------------------------------------------------------- #
async def list_orders(db: AsyncSession, user: User) -> list[Order]:
    result = await db.execute(
        select(Order).where(Order.user_id == user.id).order_by(Order.created_at.desc())
    )
    return list(result.scalars().all())


async def get_order(db: AsyncSession, user: User, order_id: uuid.UUID) -> Order | None:
    order = await db.get(Order, order_id)
    if order is None or order.user_id != user.id:
        return None
    return order
