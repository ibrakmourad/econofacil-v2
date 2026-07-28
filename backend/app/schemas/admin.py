"""Schemas administrativos."""
from __future__ import annotations

from pydantic import BaseModel


class ExpirationsSummary(BaseModel):
    carts_expired: int
    promotions_expired: int
    pix_charges_expired: int
