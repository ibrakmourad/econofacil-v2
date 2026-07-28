"""Normalização de unidades para comparação de preço unitário (RN-001).

Cada produto do catálogo universal tem um tamanho e uma unidade de embalagem
(ex.: 2 L, 500 g, 6 un). Para comparar preços de forma justa entre lojas e
entre embalagens diferentes, convertemos tudo para uma unidade base por tipo:

    peso    -> kg
    volume  -> l
    contagem-> un

O ``base_size`` resultante é gravado no produto, de modo que o preço unitário
seja simplesmente ``preço / base_size`` — calculável inclusive em SQL.
"""
from __future__ import annotations

# unidade de embalagem -> (tipo, fator para a unidade base)
_UNIT_FACTORS: dict[str, tuple[str, float]] = {
    "g": ("weight", 0.001),
    "kg": ("weight", 1.0),
    "mg": ("weight", 0.000001),
    "ml": ("volume", 0.001),
    "l": ("volume", 1.0),
    "un": ("count", 1.0),
    "unidade": ("count", 1.0),
}

_BASE_UNIT_BY_TYPE = {"weight": "kg", "volume": "l", "count": "un"}


class UnknownUnitError(ValueError):
    pass


def normalize(package_size: float, package_unit: str) -> tuple[str, str, float]:
    """Converte (tamanho, unidade) para (unit_type, base_unit, base_size).

    >>> normalize(2, "L")
    ('volume', 'l', 2.0)
    >>> normalize(500, "g")
    ('weight', 'kg', 0.5)
    """
    if package_size <= 0:
        raise ValueError("package_size deve ser maior que zero")
    key = package_unit.strip().lower()
    if key not in _UNIT_FACTORS:
        raise UnknownUnitError(f"Unidade não suportada: {package_unit!r}")
    unit_type, factor = _UNIT_FACTORS[key]
    base_unit = _BASE_UNIT_BY_TYPE[unit_type]
    base_size = round(package_size * factor, 6)
    return unit_type, base_unit, base_size


def unit_price(price: float, base_size: float) -> float:
    """Preço por unidade base (R$/kg, R$/l ou R$/un)."""
    if base_size <= 0:
        return price
    return round(price / base_size, 4)
