"""Serviço de fulfillment por loja (RN-019).

Um pedido pode ser atendido por várias lojas (split, RN-018). Até aqui o
``Order.status`` era único para o pedido inteiro, o que não fazia sentido
quando cada comerciante evolui seu próprio processo de separação/entrega de
forma independente. Este serviço introduz um registro de status por loja
(``OrderFulfillment``) e deriva o status geral do pedido a partir deles:

- o pedido só chega a ``delivered`` quando **todas** as lojas entregaram;
- enquanto isso, o status geral reflete a loja mais atrasada (a "pior" etapa
  entre as não canceladas);
- se todas as lojas forem canceladas, o pedido inteiro é marcado como
  ``cancelled``; se só algumas forem, as demais seguem seu próprio caminho e
  o status geral ignora as canceladas no cálculo acima.

Desde a RN-022 (liquidação Pix por loja), o pagamento também é por loja —
então uma loja só sai de ``awaiting_payment`` quando **a cobrança daquela
loja especificamente** é paga (ou cancelada, se vencer sem confirmação),
não mais quando o pedido inteiro muda de status.
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import ORDER_STATUS_RANK, Order, OrderFulfillment, OrderStatus


class FulfillmentNotFound(LookupError):
    """Não há fulfillment desta loja para este pedido."""


async def create_fulfillments(db: AsyncSession, order: Order, stores: list[dict]) -> None:
    """Cria um registro de fulfillment por loja do pedido recém-criado.

    Chamado durante o checkout, antes do pagamento ser processado — por isso
    o status inicial é sempre ``awaiting_payment`` (cada loja sai desse
    estado quando *sua própria* cobrança é paga, ver
    ``advance_store_if_awaiting``).
    """
    for store in stores:
        db.add(OrderFulfillment(
            order_id=order.id,
            store_id=store["store_id"],
            store_name=store["store_name"],
            status=OrderStatus.AWAITING_PAYMENT,
        ))
    await db.flush()


def recompute_order_status(order: Order) -> OrderStatus:
    """Deriva o status geral do pedido a partir dos fulfillments por loja."""
    statuses = [f.status for f in order.fulfillments]
    if not statuses:
        return order.status
    active = [s for s in statuses if s != OrderStatus.CANCELLED]
    if not active:
        return OrderStatus.CANCELLED
    return min(active, key=lambda s: ORDER_STATUS_RANK[s])


async def advance_store_if_awaiting(
    db: AsyncSession, order: Order, store_id: uuid.UUID, new_status: OrderStatus
) -> None:
    """Move o fulfillment de uma loja para ``new_status`` só se ainda estiver
    em ``awaiting_payment`` (RN-022: gatilho é o pagamento daquela loja
    específica sendo confirmado ou vencendo sem confirmação).

    Não commita — o chamador decide quando (normalmente após outras
    mudanças na mesma transação, ex.: o próprio ``Payment``).
    """
    fulfillment = next((f for f in order.fulfillments if f.store_id == store_id), None)
    if fulfillment is not None and fulfillment.status == OrderStatus.AWAITING_PAYMENT:
        fulfillment.status = new_status
    order.status = recompute_order_status(order)


async def set_store_status(
    db: AsyncSession, order: Order, store_id: uuid.UUID, status: OrderStatus
) -> OrderFulfillment:
    """Atualiza o status de uma loja específica (chamado pelo comerciante) e
    recalcula o status geral do pedido."""
    fulfillment = next((f for f in order.fulfillments if f.store_id == store_id), None)
    if fulfillment is None:
        raise FulfillmentNotFound
    fulfillment.status = status
    order.status = recompute_order_status(order)
    await db.commit()
    await db.refresh(order)
    return fulfillment
