"""Serviço de pagamentos: criação, confirmação (webhook) e consulta.

RN-022 — liquidação Pix por loja: em vez de uma única cobrança para o
pedido inteiro, cada loja do pedido recebe sua PRÓPRIA cobrança (seu
próprio valor, seu próprio QR/BR Code, seu próprio txid) — na chave Pix da
própria loja quando configurada (``Store.pix_key``), ou na chave da
plataforma como intermediária, se a loja não tiver uma própria. Isso é como
um marketplace de verdade faz split de pagamento: cada comerciante recebe
diretamente a sua parte, em vez de a plataforma receber o total e ter que
repassar manualmente depois. Um pedido de loja única continua gerando
exatamente 1 pagamento — o caso N=1 deste modelo mais geral.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.catalog import Store
from app.models.order import Order, OrderStatus
from app.models.payment import Payment, PaymentMethod, PaymentStatus
from app.models.user import User
from app.payments.provider import get_pix_provider
from app.services import expiration_service, fulfillment_service


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _store_subtotals(order: Order) -> dict[uuid.UUID, dict]:
    """Agrupa os itens do pedido por loja e soma o subtotal de cada uma."""
    lines: dict[uuid.UUID, dict] = {}
    for item in order.items:
        slot = lines.setdefault(item.store_id, {"store_name": item.store_name, "subtotal": 0.0})
        slot["subtotal"] += float(item.line_total)
    return lines


async def create_for_order(db: AsyncSession, order: Order, method: PaymentMethod) -> list[Payment]:
    """Cria uma cobrança **por loja** do pedido (RN-022)."""
    if method == PaymentMethod.CARD:
        raise ValueError("Pagamento com cartão ainda não disponível")

    store_lines = _store_subtotals(order)
    payments: list[Payment] = []

    for store_id, info in store_lines.items():
        amount = round(info["subtotal"], 2)
        store_name = info["store_name"]

        if method == PaymentMethod.PIX:
            store = await db.get(Store, store_id)
            pix_key = store.pix_key if (store and store.pix_key) else settings.PIX_KEY
            charge = get_pix_provider().create_charge(
                amount=amount,
                txid=f"{order.code}-{str(store_id)[:6]}",
                pix_key=pix_key,
                merchant_name=store_name,
            )
            payment = Payment(
                order_id=order.id, store_id=store_id, store_name=store_name,
                method=method, status=PaymentStatus.PENDING, amount=amount,
                provider=charge.provider, txid=charge.txid,
                br_code=charge.br_code, qr_svg=charge.qr_svg, expires_at=charge.expires_at,
            )
        else:  # ECONOPAY — carteira do ecossistema, liquidação imediata (stub), por loja também
            payment = Payment(
                order_id=order.id, store_id=store_id, store_name=store_name,
                method=method, status=PaymentStatus.PAID, amount=amount,
                provider="econopay-wallet", paid_at=_utcnow(),
            )
            await fulfillment_service.advance_store_if_awaiting(db, order, store_id, OrderStatus.PLACED)

        db.add(payment)
        payments.append(payment)

    order.status = fulfillment_service.recompute_order_status(order)
    await db.commit()
    for p in payments:
        await db.refresh(p)
    await db.refresh(order)
    return payments


async def list_for_order(db: AsyncSession, order_id: uuid.UUID) -> list[Payment]:
    """Lista os pagamentos (um por loja) de um pedido, expirando cobranças
    Pix vencidas oportunisticamente na leitura."""
    result = await db.execute(select(Payment).where(Payment.order_id == order_id))
    payments = list(result.scalars().all())
    for payment in payments:
        await expiration_service.expire_single_pix_charge(db, payment)
    return payments


async def get_payment(db: AsyncSession, user: User, payment_id: uuid.UUID) -> Payment | None:
    payment = await db.get(Payment, payment_id)
    if payment is None:
        return None
    order = await db.get(Order, payment.order_id)
    if order is None or order.user_id != user.id:
        return None
    await expiration_service.expire_single_pix_charge(db, payment)
    return payment


async def confirm_pix(db: AsyncSession, txid: str) -> Payment | None:
    """Confirma o pagamento de **uma loja** a partir do callback do PSP
    (idempotente). Só a loja daquela cobrança avança para ``placed`` — as
    demais lojas do mesmo pedido split, se houver, seguem aguardando a
    confirmação da própria cobrança."""
    result = await db.execute(select(Payment).where(Payment.txid == txid))
    payment = result.scalar_one_or_none()
    if payment is None:
        return None
    if payment.status == PaymentStatus.PENDING:
        payment.status = PaymentStatus.PAID
        payment.paid_at = _utcnow()
        order = await db.get(Order, payment.order_id)
        if order is not None:
            await fulfillment_service.advance_store_if_awaiting(
                db, order, payment.store_id, OrderStatus.PLACED
            )
        await db.commit()
        await db.refresh(payment)
    return payment
