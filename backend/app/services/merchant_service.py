"""Serviço do Portal do Comerciante (escopo de propriedade da loja)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Product, Store, StoreProduct
from app.models.order import Order, OrderItem, OrderStatus
from app.models.promotion import Promotion, PromotionStatus
from app.models.user import User, UserRole
from app.services import fulfillment_service
from app.services import expiration_service
from app.services.fulfillment_service import FulfillmentNotFound


class NotOwner(PermissionError):
    pass


class StoreNotFound(LookupError):
    pass


class AmbiguousStore(ValueError):
    """O comerciante possui mais de uma loja neste pedido; store_id é obrigatório."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def get_owned_store(db: AsyncSession, user: User, store_id: uuid.UUID) -> Store:
    store = await db.get(Store, store_id)
    if store is None:
        raise StoreNotFound
    if user.role != UserRole.ADMIN and store.owner_id != user.id:
        raise NotOwner
    return store


async def my_store_ids(db: AsyncSession, user: User) -> list[uuid.UUID]:
    result = await db.execute(select(Store.id).where(Store.owner_id == user.id))
    return [r[0] for r in result.all()]


async def list_my_stores(db: AsyncSession, user: User) -> list[Store]:
    result = await db.execute(
        select(Store).where(Store.owner_id == user.id).order_by(Store.name)
    )
    return list(result.scalars().all())


# --------------------------------------------------------------------------- #
# Inventário (catálogo / estoque / preços da loja)
# --------------------------------------------------------------------------- #
async def list_inventory(db: AsyncSession, store_id: uuid.UUID) -> list[dict]:
    result = await db.execute(
        select(StoreProduct, Product)
        .join(Product, Product.id == StoreProduct.product_id)
        .where(StoreProduct.store_id == store_id)
        .order_by(Product.name)
    )
    return [
        {
            "product_id": p.id,
            "product_name": p.name,
            "package_size": p.package_size,
            "package_unit": p.package_unit,
            "price": float(sp.price),
            "original_price": float(sp.original_price) if sp.original_price else None,
            "in_stock": sp.in_stock,
            "stock_quantity": sp.stock_quantity,
        }
        for sp, p in result.all()
    ]


# --------------------------------------------------------------------------- #
# Promoções
# --------------------------------------------------------------------------- #
async def _get_offer(db: AsyncSession, store_id: uuid.UUID, product_id: uuid.UUID) -> StoreProduct | None:
    result = await db.execute(
        select(StoreProduct).where(
            StoreProduct.store_id == store_id, StoreProduct.product_id == product_id
        )
    )
    return result.scalar_one_or_none()


async def expire_due_promotions(db: AsyncSession, store_id: uuid.UUID) -> None:
    """Encerra promoções vencidas desta loja, restaurando o preço-base
    (oportunista, na leitura). A lógica em si mora em ``expiration_service``,
    compartilhada com o agendador de background."""
    await expiration_service.expire_promotions(db, store_id=store_id)


async def list_promotions(db: AsyncSession, store_id: uuid.UUID) -> list[Promotion]:
    await expire_due_promotions(db, store_id)
    result = await db.execute(
        select(Promotion)
        .where(Promotion.store_id == store_id)
        .order_by(Promotion.created_at.desc())
    )
    return list(result.scalars().all())


async def create_promotion(
    db: AsyncSession, store_id: uuid.UUID, product_id: uuid.UUID,
    promo_price: float, ends_at: datetime,
) -> Promotion:
    offer = await _get_offer(db, store_id, product_id)
    if offer is None:
        raise ValueError("Não há oferta deste produto na loja")
    if promo_price >= float(offer.price):
        raise ValueError("O preço promocional deve ser menor que o preço atual")
    if _aware(ends_at) <= _utcnow():
        raise ValueError("A data de término deve ser no futuro")

    promo = Promotion(
        store_id=store_id, product_id=product_id,
        promo_price=promo_price, base_price=float(offer.price), ends_at=ends_at,
    )
    db.add(promo)
    # aplica a promoção: preço atual vira o riscado, promo vira o vigente
    offer.original_price = offer.price
    offer.price = promo_price
    await db.commit()
    await db.refresh(promo)
    return promo


async def end_promotion(db: AsyncSession, user: User, promo_id: uuid.UUID) -> Promotion:
    promo = await db.get(Promotion, promo_id)
    if promo is None:
        raise StoreNotFound
    await get_owned_store(db, user, promo.store_id)  # valida propriedade
    if promo.status == PromotionStatus.ACTIVE:
        offer = await _get_offer(db, promo.store_id, promo.product_id)
        if offer is not None:
            offer.price = promo.base_price
            offer.original_price = None
        promo.status = PromotionStatus.ENDED
        await db.commit()
        await db.refresh(promo)
    return promo


# --------------------------------------------------------------------------- #
# Pedidos do comerciante (RN-019: uma linha por loja do comerciante no pedido,
# já que cada loja evolui seu próprio status de atendimento)
# --------------------------------------------------------------------------- #
async def list_orders(db: AsyncSession, store_ids: list[uuid.UUID]) -> list[dict]:
    if not store_ids:
        return []
    result = await db.execute(
        select(Order)
        .join(OrderItem, OrderItem.order_id == Order.id)
        .where(OrderItem.store_id.in_(store_ids))
        .distinct()
        .order_by(Order.created_at.desc())
    )
    orders = list(result.scalars().all())
    out = []
    for order in orders:
        fulfillment_by_store = {f.store_id: f for f in order.fulfillments}
        # uma linha por loja própria presente no pedido (split gera várias)
        my_stores = sorted({i.store_id for i in order.items if i.store_id in store_ids}, key=str)
        for store_id in my_stores:
            mine = [i for i in order.items if i.store_id == store_id]
            fulfillment = fulfillment_by_store.get(store_id)
            out.append({
                "order_id": order.id,
                "code": order.code,
                "store_id": store_id,
                "store_name": mine[0].store_name if mine else "",
                "status": fulfillment.status if fulfillment else order.status,
                "created_at": order.created_at,
                "store_subtotal": round(sum(float(i.line_total) for i in mine), 2),
                "items": [
                    {
                        "product_name": i.product_name,
                        "quantity": i.quantity,
                        "unit_price": float(i.unit_price),
                        "line_total": float(i.line_total),
                    }
                    for i in mine
                ],
            })
    return out


async def update_order_status(
    db: AsyncSession,
    store_ids: list[uuid.UUID],
    order_id: uuid.UUID,
    status: OrderStatus,
    store_id: uuid.UUID | None = None,
) -> dict:
    """Atualiza o status de atendimento de **uma loja** dentro do pedido.

    Se o comerciante possui só uma das lojas presentes no pedido, ``store_id``
    pode ser omitido (inferido automaticamente). Se possuir mais de uma
    (pedido split entre duas lojas do mesmo comerciante), é obrigatório
    informar qual delas.
    """
    order = await db.get(Order, order_id)
    if order is None:
        raise StoreNotFound

    order_store_ids = {i.store_id for i in order.items}
    mine_in_order = sorted(order_store_ids & set(store_ids), key=str)
    if not mine_in_order:
        raise NotOwner

    if store_id is None:
        if len(mine_in_order) > 1:
            raise AmbiguousStore
        store_id = mine_in_order[0]
    elif store_id not in mine_in_order:
        raise NotOwner

    try:
        fulfillment = await fulfillment_service.set_store_status(db, order, store_id, status)
    except FulfillmentNotFound:
        raise StoreNotFound

    return {
        "order_id": order.id,
        "code": order.code,
        "store_id": store_id,
        "store_name": fulfillment.store_name,
        "status": fulfillment.status,
        "created_at": order.created_at,
        "store_subtotal": round(
            sum(float(i.line_total) for i in order.items if i.store_id == store_id), 2
        ),
        "items": [
            {
                "product_name": i.product_name,
                "quantity": i.quantity,
                "unit_price": float(i.unit_price),
                "line_total": float(i.line_total),
            }
            for i in order.items if i.store_id == store_id
        ],
    }


# --------------------------------------------------------------------------- #
# Relatório operacional
# --------------------------------------------------------------------------- #
async def store_report(db: AsyncSession, store_id: uuid.UUID) -> dict:
    agg = (await db.execute(
        select(
            func.count(func.distinct(OrderItem.order_id)),
            func.coalesce(func.sum(OrderItem.line_total), 0),
            func.coalesce(func.sum(OrderItem.quantity), 0),
        ).where(OrderItem.store_id == store_id)
    )).one()
    orders_count, revenue, units = agg

    top = (await db.execute(
        select(
            OrderItem.product_name,
            func.sum(OrderItem.quantity).label("qty"),
            func.sum(OrderItem.line_total).label("rev"),
        )
        .where(OrderItem.store_id == store_id)
        .group_by(OrderItem.product_name)
        .order_by(func.sum(OrderItem.quantity).desc())
        .limit(5)
    )).all()

    return {
        "orders_count": int(orders_count),
        "revenue": round(float(revenue), 2),
        "units_sold": int(units),
        "top_products": [
            {"product_name": n, "quantity": int(q), "revenue": round(float(r), 2)}
            for n, q, r in top
        ],
    }
