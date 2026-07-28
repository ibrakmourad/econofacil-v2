"""Serviço de expirações (RN-021).

Antes, carrinho (RN-008), promoções e cobranças Pix vencidas só eram
corrigidas de forma **oportunista**: o registro continuava "errado" no banco
até que alguém lesse aquele carrinho/loja/pedido específico. Este módulo
centraliza a lógica de expiração para que ela possa ser chamada:

1. Sob demanda, na leitura de um registro específico (mantém o
   comportamento antigo, sem esperar o próximo tick do agendador); e
2. Em lote, por um agendador de background (``app/core/scheduler.py``) ou
   por um disparo manual (``POST /admin/expirations/run``), corrigindo
   todos os registros vencidos do banco de uma vez.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cart import Cart, CartStatus
from app.models.catalog import StoreProduct
from app.models.order import Order, OrderStatus
from app.models.payment import Payment, PaymentStatus
from app.models.promotion import Promotion, PromotionStatus
from app.services import fulfillment_service


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Carrinho (RN-008)
# --------------------------------------------------------------------------- #
async def expire_carts(db: AsyncSession) -> int:
    """Expira, em lote, todos os carrinhos ativos vencidos (24h logado)."""
    result = await db.execute(select(Cart).where(Cart.status == CartStatus.ACTIVE))
    count = 0
    for cart in result.scalars().all():
        if _aware(cart.expires_at) <= _utcnow():
            cart.status = CartStatus.EXPIRED
            count += 1
    if count:
        await db.commit()
    return count


# --------------------------------------------------------------------------- #
# Promoções
# --------------------------------------------------------------------------- #
async def _restore_price_if_due(db: AsyncSession, promo: Promotion) -> bool:
    if _aware(promo.ends_at) > _utcnow():
        return False
    result = await db.execute(
        select(StoreProduct).where(
            StoreProduct.store_id == promo.store_id,
            StoreProduct.product_id == promo.product_id,
        )
    )
    offer = result.scalar_one_or_none()
    if offer is not None:
        offer.price = promo.base_price
        offer.original_price = None
    promo.status = PromotionStatus.ENDED
    return True


async def expire_promotions(db: AsyncSession, *, store_id: uuid.UUID | None = None) -> int:
    """Encerra promoções vencidas, restaurando o preço-base da oferta.

    Se ``store_id`` for informado, escopa a uma única loja (uso oportunista
    na leitura, ex.: ``GET /merchant/stores/{id}/promotions``); sem ele,
    varre todas as lojas (uso pelo agendador em lote).
    """
    stmt = select(Promotion).where(Promotion.status == PromotionStatus.ACTIVE)
    if store_id is not None:
        stmt = stmt.where(Promotion.store_id == store_id)
    result = await db.execute(stmt)
    count = 0
    for promo in result.scalars().all():
        if await _restore_price_if_due(db, promo):
            count += 1
    if count:
        await db.commit()
    return count


# --------------------------------------------------------------------------- #
# Cobranças Pix
# --------------------------------------------------------------------------- #
def _mark_pix_expired(payment: Payment) -> bool:
    if payment.status != PaymentStatus.PENDING or payment.expires_at is None:
        return False
    if _aware(payment.expires_at) > _utcnow():
        return False
    payment.status = PaymentStatus.EXPIRED
    return True


async def _cancel_store_for_expired_payment(db: AsyncSession, payment: Payment) -> None:
    """Cancela o fulfillment **da loja daquela cobrança** (RN-022) quando a
    cobrança Pix vence sem confirmação — as demais lojas do mesmo pedido
    split, se já pagas ou ainda dentro do prazo, não são afetadas."""
    order = await db.get(Order, payment.order_id)
    if order is not None:
        await fulfillment_service.advance_store_if_awaiting(
            db, order, payment.store_id, OrderStatus.CANCELLED
        )


async def expire_single_pix_charge(db: AsyncSession, payment: Payment) -> bool:
    """Expira uma cobrança Pix pontual, se vencida (uso oportunista na
    leitura, ex.: ``GET /payments/{id}`` e ``GET /orders/{id}``)."""
    if not _mark_pix_expired(payment):
        return False
    await _cancel_store_for_expired_payment(db, payment)
    await db.commit()
    await db.refresh(payment)
    return True


async def expire_pix_charges(db: AsyncSession) -> int:
    """Varre, em lote, todas as cobranças Pix pendentes vencidas (uso pelo
    agendador)."""
    result = await db.execute(select(Payment).where(Payment.status == PaymentStatus.PENDING))
    count = 0
    for payment in result.scalars().all():
        if _mark_pix_expired(payment):
            await _cancel_store_for_expired_payment(db, payment)
            count += 1
    if count:
        await db.commit()
    return count


# --------------------------------------------------------------------------- #
# Execução em lote (agendador / disparo manual)
# --------------------------------------------------------------------------- #
async def run_all(db: AsyncSession) -> dict[str, int]:
    """Roda as três expirações numa única passada."""
    return {
        "carts_expired": await expire_carts(db),
        "promotions_expired": await expire_promotions(db),
        "pix_charges_expired": await expire_pix_charges(db),
    }
