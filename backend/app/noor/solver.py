"""Noor Solver — motor de otimização de cestas (Noor Core).

Resolve, de forma **exata**, a alocação de itens entre lojas que minimiza o
custo total respeitando um teto de lojas (RN-018), via Programação Linear
Inteira (ILP) com o solver CBC (PuLP).

Formulação:
    min  Σ  preço[i,s]·qtd[i]·x[i,s]
    s.a. Σ_s x[i,s] = 1                 (cada item é comprado em uma loja)
         x[i,s] ≤ y[s]                  (só compra em loja "aberta")
         Σ_s y[s] ≤ K                   (no máximo K lojas — RN-018)
         x[i,s] ∈ {0,1}, y[s] ∈ {0,1}

Se o solver não estiver disponível, levanta ``SolverUnavailable`` para que a
camada de otimização caia na heurística de enumeração.

Versionamento (Noor Models): ``NOOR_SOLVER_VERSION``. A integração com MLflow
para tracking/registry de modelos é prevista para versões futuras da Noor.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

NOOR_SOLVER_VERSION = "noor-solver-1.0.0"


class SolverUnavailable(RuntimeError):
    """O solver de ILP não pôde ser usado (lib ausente ou falha de execução)."""


def solver_available() -> bool:
    try:
        import pulp  # noqa: F401
        from pulp import PULP_CBC_CMD

        return bool(PULP_CBC_CMD(msg=0).available())
    except Exception:
        return False


@dataclass
class MinCost:
    total: float
    per_store: dict
    method: str
    optimal: bool
    solve_ms: float
    meta: dict = field(default_factory=dict)


def solve_min_cost(
    items: list[dict],
    offers: dict,
    max_stores: int,
    *,
    time_limit: float = 5.0,
) -> MinCost | None:
    """Custo mínimo para comprar ``items`` usando no máximo ``max_stores`` lojas.

    Retorna ``None`` se for inviável (ex.: cobertura impossível dentro do teto).
    Levanta ``SolverUnavailable`` se o solver não puder rodar.
    """
    try:
        import pulp
        from pulp import (
            PULP_CBC_CMD,
            LpBinary,
            LpMinimize,
            LpProblem,
            LpStatus,
            LpVariable,
            lpSum,
        )
    except Exception as exc:  # pragma: no cover - ambiente sem pulp
        raise SolverUnavailable(str(exc)) from exc

    if not items:
        return MinCost(0.0, {}, "noor-ilp", True, 0.0)

    # índices estáveis para nomes de variáveis seguros
    store_ids = sorted({s for it in items for s in offers.get(it["product_id"], {})}, key=str)
    s_idx = {sid: i for i, sid in enumerate(store_ids)}

    start = time.perf_counter()
    try:
        prob = LpProblem("noor_basket", LpMinimize)
        y = {sid: LpVariable(f"y_{s_idx[sid]}", cat=LpBinary) for sid in store_ids}
        x: dict = {}
        cost_terms = []

        for i, it in enumerate(items):
            pid = it["product_id"]
            qty = it["quantity"]
            pairs = offers.get(pid, {})
            if not pairs:
                # item sem oferta: ignorado aqui (tratado como indisponível fora)
                continue
            item_vars = []
            for sid, o in pairs.items():
                var = LpVariable(f"x_{i}_{s_idx[sid]}", cat=LpBinary)
                x[(i, sid)] = var
                item_vars.append(var)
                cost_terms.append(o["price"] * qty * var)
                prob += var <= y[sid]
            prob += lpSum(item_vars) == 1  # comprado em exatamente uma loja

        prob += lpSum(cost_terms)              # objetivo
        prob += lpSum(y.values()) <= max_stores  # teto de lojas (RN-018)

        prob.solve(PULP_CBC_CMD(msg=0, timeLimit=time_limit))
        status = LpStatus[prob.status]
    except SolverUnavailable:
        raise
    except Exception as exc:
        raise SolverUnavailable(str(exc)) from exc

    solve_ms = round((time.perf_counter() - start) * 1000, 2)

    if status != "Optimal":
        return None

    # reconstrói o plano por loja
    per_store: dict = {}
    total = 0.0
    for (i, sid), var in x.items():
        if var.value() and var.value() > 0.5:
            it = items[i]
            o = offers[it["product_id"]][sid]
            line = round(o["price"] * it["quantity"], 2)
            total += line
            slot = per_store.setdefault(
                sid,
                {"store_id": sid, "store_name": o["store_name"], "items": [], "subtotal": 0.0},
            )
            slot["items"].append({
                "product_id": it["product_id"],
                "product_name": it["name"],
                "quantity": it["quantity"],
                "unit_price": o["price"],
                "line_total": line,
            })
            slot["subtotal"] = round(slot["subtotal"] + line, 2)

    return MinCost(round(total, 2), per_store, "noor-ilp", True, solve_ms,
                   meta={"version": NOOR_SOLVER_VERSION})
