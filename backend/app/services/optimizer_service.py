"""Camada de otimização de cestas (RN-018).

Fachada que decide entre o **Noor Solver** (ILP exato, padrão) e a **heurística**
de enumeração de subconjuntos (fallback). Ambos resolvem o mesmo subproblema —
"custo mínimo usando no máximo K lojas" — e a lógica de decisão (loja única ×
split, limiar de 2%, recomendação) é compartilhada e fica aqui.
"""
from __future__ import annotations

import time
from collections import Counter
from itertools import combinations

from app.core.config import settings
from app.noor import solver as noor_solver
from app.noor.solver import MinCost, SolverUnavailable

MIN_SPLIT_SAVINGS = 0.02  # RN-018: economia mínima de 2%
MAX_STORES = 3            # RN-018: até 3 lojas
_BRUTE_FORCE_LIMIT = 20   # acima disso a heurística poda as lojas

_METRICS = {
    "optimizations": 0,
    "noor_ilp": 0,
    "heuristic": 0,
    "last_method": None,
    "last_ms": 0.0,
}


def get_metrics() -> dict:
    """Métricas agregadas (Noor Monitor)."""
    return dict(_METRICS)


def _record(method: str | None, ms: float) -> None:
    _METRICS["optimizations"] += 1
    if method == "noor-ilp":
        _METRICS["noor_ilp"] += 1
    elif method:
        _METRICS["heuristic"] += 1
    _METRICS["last_method"] = method
    _METRICS["last_ms"] = ms


# --------------------------------------------------------------------------- #
# Heurística (fallback)
# --------------------------------------------------------------------------- #
def _prune_stores(items: list[dict], offers: dict, limit: int = 12) -> list:
    score: Counter = Counter()
    for it in items:
        m = offers[it["product_id"]]
        cheapest = min(o["price"] for o in m.values())
        for sid, o in m.items():
            score[sid] += 2 if o["price"] == cheapest else 1
    keep = {sid for sid, _ in score.most_common(limit)}
    for it in items:
        m = offers[it["product_id"]]
        if not (set(m) & keep):
            keep.add(min(m.items(), key=lambda kv: kv[1]["price"])[0])
    return sorted(keep, key=str)


def _assign(items: list[dict], offers: dict, subset: tuple):
    per_store: dict = {}
    total = 0.0
    for it in items:
        pid = it["product_id"]
        qty = it["quantity"]
        best = None
        for sid in subset:
            o = offers[pid].get(sid)
            if o and (best is None or o["price"] < best[1]):
                best = (sid, o["price"], o["store_name"])
        if best is None:
            return False, None, None
        sid, price, sname = best
        line = round(price * qty, 2)
        total += line
        slot = per_store.setdefault(
            sid, {"store_id": sid, "store_name": sname, "items": [], "subtotal": 0.0}
        )
        slot["items"].append({
            "product_id": pid, "product_name": it["name"],
            "quantity": qty, "unit_price": price, "line_total": line,
        })
        slot["subtotal"] = round(slot["subtotal"] + line, 2)
    return True, round(total, 2), per_store


def _heuristic_min_cost(items: list[dict], offers: dict, max_stores: int) -> MinCost | None:
    start = time.perf_counter()
    store_ids = sorted({s for it in items for s in offers[it["product_id"]]}, key=str)
    if len(store_ids) > _BRUTE_FORCE_LIMIT:
        store_ids = _prune_stores(items, offers)
    best = None
    for k in range(1, min(max_stores, len(store_ids)) + 1):
        for subset in combinations(store_ids, k):
            feasible, total, per_store = _assign(items, offers, subset)
            if not feasible:
                continue
            if (
                best is None
                or total < best[0]
                or (total == best[0] and len(per_store) < len(best[1]))
            ):
                best = (total, per_store)
    ms = round((time.perf_counter() - start) * 1000, 2)
    if best is None:
        return None
    return MinCost(best[0], best[1], "heuristic", True, ms)


# --------------------------------------------------------------------------- #
# Seleção do motor
# --------------------------------------------------------------------------- #
def _min_cost(items: list[dict], offers: dict, max_stores: int) -> MinCost | None:
    if settings.NOOR_SOLVER_ENABLED and not settings.NOOR_FORCE_HEURISTIC:
        try:
            return noor_solver.solve_min_cost(items, offers, max_stores)
        except SolverUnavailable:
            res = _heuristic_min_cost(items, offers, max_stores)
            if res is not None:
                res.method = "heuristic-fallback"
            return res
    return _heuristic_min_cost(items, offers, max_stores)


def _option(mc: MinCost) -> dict:
    stores = sorted(mc.per_store.values(), key=lambda s: -s["subtotal"])
    return {"stores": stores, "total": mc.total, "store_count": len(stores)}


# --------------------------------------------------------------------------- #
# Plano de compra (decisão RN-018)
# --------------------------------------------------------------------------- #
def plan_purchase(items: list[dict], offers: dict) -> dict:
    available = [it for it in items if offers.get(it["product_id"])]
    engine_base = {"version": noor_solver.NOOR_SOLVER_VERSION}

    if not available:
        _record(None, 0.0)
        return {
            "single_store": None, "split": None, "recommended": None,
            "savings": 0.0, "savings_pct": 0.0, "meets_min_savings": False,
            "fulfillable": False,
            "engine": {"method": None, "optimal": False, "solve_ms": 0.0, **engine_base},
        }

    single = _min_cost(available, offers, 1)
    overall = _min_cost(available, offers, MAX_STORES)

    total_ms = round((single.solve_ms if single else 0.0) + (overall.solve_ms if overall else 0.0), 2)
    method = overall.method if overall else (single.method if single else None)
    _record(method, total_ms)

    fulfillable = overall is not None
    single_opt = _option(single) if single else None
    split_opt = _option(overall) if (overall and len(overall.per_store) > 1) else None

    savings = savings_pct = 0.0
    meets = False
    recommended = None
    if fulfillable:
        if single and split_opt:
            savings = round(single.total - overall.total, 2)
            savings_pct = round(savings / single.total, 4) if single.total else 0.0
            meets = savings_pct >= MIN_SPLIT_SAVINGS
            recommended = "split" if meets else "single"
        elif single:
            recommended = "single"
        else:
            recommended = "split"

    return {
        "single_store": single_opt,
        "split": split_opt,
        "recommended": recommended,
        "savings": savings,
        "savings_pct": savings_pct,
        "meets_min_savings": meets,
        "fulfillable": fulfillable,
        "engine": {
            "method": method,
            "optimal": bool(overall and overall.optimal),
            "solve_ms": total_ms,
            **engine_base,
        },
    }
