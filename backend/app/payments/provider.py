"""Abstração de provedor Pix (PSP). Hoje há um provedor *mock* que gera o BR
Code localmente; um PSP real (ex.: via API) implementaria a mesma interface
sem mudar o restante do sistema."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from app.core.config import settings
from app.payments import pix


@dataclass
class PixCharge:
    provider: str
    txid: str
    br_code: str
    qr_svg: str
    expires_at: datetime


class PixProvider(Protocol):
    name: str

    def create_charge(
        self, *, amount: float, txid: str, pix_key: str | None = None, merchant_name: str | None = None
    ) -> PixCharge: ...


class MockPixProvider:
    """Provedor de desenvolvimento: gera um BR Code Pix válido, sem PSP real."""

    name = "mock-pix"

    def create_charge(
        self, *, amount: float, txid: str, pix_key: str | None = None, merchant_name: str | None = None
    ) -> PixCharge:
        clean_txid = pix.sanitize_txid(txid)
        payload = pix.build_pix_payload(
            key=pix_key or settings.PIX_KEY,
            merchant_name=merchant_name or "EconoFacil",
            merchant_city="Sao Paulo",
            amount=amount,
            txid=clean_txid,
        )
        return PixCharge(
            provider=self.name,
            txid=clean_txid,
            br_code=payload,
            qr_svg=pix.build_qr_svg(payload),
            expires_at=datetime.now(timezone.utc)
            + timedelta(seconds=settings.PIX_CHARGE_TTL_SECONDS),
        )


def get_pix_provider() -> PixProvider:
    # Ponto de troca para um PSP real no futuro (sem alterar os serviços).
    return MockPixProvider()
