"""Agendador de expirações (RN-021) — o "cron/worker" citado no roadmap.

Carrinho (RN-008), promoções e cobranças Pix vencidas eram corrigidos só de
forma oportunista, na leitura (ver ``app/services/expiration_service.py``).
Isso deixava registros "errados" no banco até que alguém lesse aquele
carrinho/loja/pedido específico — inofensivo para o usuário dono do registro,
mas ruim para quem olha o banco de fora (ex.: relatório do comerciante,
Noor Monitor) ou depende do estado global (ex.: liberar estoque reservado).

Este módulo roda um laço assíncrono de background **dentro do próprio
processo da API**, sem depender de infraestrutura externa (cron do SO,
Celery + Redis, etc.) — suficiente para o MVP rodando em um único worker.

Limitação conhecida (documentada para não surpreender em produção): se a API
rodar em múltiplas réplicas, cada uma dispara seu próprio laço e o mesmo
registro pode ser expirado mais de uma vez na mesma janela. Isso é
inofensivo aqui (todas as operações de expiração são idempotentes — expirar
duas vezes o mesmo carrinho não tem efeito extra), mas se o volume justificar
uma solução "de verdade" (lock distribuído, job único ex.: Celery beat ou
cron gerenciado do provedor), é o próximo passo natural.
"""
from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services import expiration_service

logger = logging.getLogger("econofacil.scheduler")

_task: asyncio.Task | None = None


async def run_once() -> dict[str, int]:
    """Roda uma passada das expirações com sua própria sessão de banco.

    Extraído do laço para poder ser testado/chamado isoladamente (ex.: num
    teste, ou por um endpoint administrativo) sem esperar o próximo tick.
    """
    async with AsyncSessionLocal() as db:
        return await expiration_service.run_all(db)


async def _loop() -> None:
    while True:
        try:
            summary = await run_once()
            if any(summary.values()):
                logger.info("expirações aplicadas: %s", summary)
        except asyncio.CancelledError:
            raise
        except Exception:  # nunca deixa um erro pontual matar o worker
            logger.exception("falha ao rodar o job de expirações")
        await asyncio.sleep(settings.SCHEDULER_INTERVAL_SECONDS)


def start() -> None:
    """Inicia o laço de background (chamado no ``lifespan`` da app)."""
    global _task
    if _task is not None and not _task.done():
        return  # já rodando
    _task = asyncio.create_task(_loop(), name="econofacil-expiration-scheduler")


async def stop() -> None:
    """Cancela o laço de background de forma limpa (chamado no shutdown)."""
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except asyncio.CancelledError:
        pass
    _task = None


def is_running() -> bool:
    return _task is not None and not _task.done()
