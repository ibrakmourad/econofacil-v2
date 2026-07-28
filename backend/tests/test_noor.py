"""Testes do Noor Solver (ILP) e sua equivalência com a heurística."""
from app.core.config import settings
from app.models.user import UserRole
from app.noor import solver as noor_solver
from app.services import optimizer_service
from app.services.optimizer_service import _heuristic_min_cost

LOGIN = "/api/v1/auth/login"


def _o(n, p):
    return {"store_name": n, "price": p}


SCENARIOS = [
    # (items, offers)
    (
        [{"product_id": "A", "name": "A", "quantity": 1}, {"product_id": "B", "name": "B", "quantity": 2}],
        {"A": {"s1": _o("L1", 10), "s2": _o("L2", 12)}, "B": {"s1": _o("L1", 5), "s2": _o("L2", 4)}},
    ),
    (
        [{"product_id": p, "name": p, "quantity": 1} for p in "ABCD"],
        {p: {"s0": _o("Comum", 2.0), f"s{i}": _o(f"L{i}", 1.0)} for i, p in enumerate("ABCD", 1)},
    ),
]


def test_noor_solver_is_available():
    assert noor_solver.solver_available() is True


def test_noor_matches_heuristic_optimum():
    for items, offers in SCENARIOS:
        ilp = noor_solver.solve_min_cost(items, offers, max_stores=3)
        heur = _heuristic_min_cost(items, offers, max_stores=3)
        assert ilp is not None and heur is not None
        # ambos exatos -> mesmo custo ótimo
        assert ilp.total == heur.total
        assert ilp.method == "noor-ilp"


def test_noor_respects_store_cap():
    items, offers = SCENARIOS[1]
    res = noor_solver.solve_min_cost(items, offers, max_stores=3)
    assert res is not None
    assert len(res.per_store) <= 3


def test_noor_infeasible_when_cap_too_small():
    items = [{"product_id": "A", "name": "A", "quantity": 1}, {"product_id": "B", "name": "B", "quantity": 1}]
    offers = {"A": {"s1": _o("L1", 10)}, "B": {"s2": _o("L2", 8)}}
    # exige 2 lojas, mas teto = 1 -> inviável
    assert noor_solver.solve_min_cost(items, offers, max_stores=1) is None
    # com teto 2 é viável
    assert noor_solver.solve_min_cost(items, offers, max_stores=2) is not None


def test_force_heuristic_setting(monkeypatch):
    monkeypatch.setattr(settings, "NOOR_FORCE_HEURISTIC", True)
    items, offers = SCENARIOS[0]
    plan = optimizer_service.plan_purchase(items, offers)
    assert plan["engine"]["method"] == "heuristic"


async def test_noor_status_endpoint(client):
    resp = await client.get("/api/v1/noor/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["solver_available"] is True
    assert body["engine"] == "noor-ilp"
    assert body["max_stores"] == 3
    assert body["min_split_savings"] == 0.02


async def test_optimize_uses_noor_engine(client, make_privileged_user):
    await make_privileged_user("adm2@ef.com", "AdminPass1", UserRole.ADMIN)
    tok = (await client.post(LOGIN, json={"email": "adm2@ef.com", "password": "AdminPass1"})).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    arroz = (await client.post("/api/v1/catalog/products", json={"name": "Arroz", "package_size": 5, "package_unit": "kg"}, headers=h)).json()["id"]
    feijao = (await client.post("/api/v1/catalog/products", json={"name": "Feijão", "package_size": 1, "package_unit": "kg"}, headers=h)).json()["id"]
    sa = (await client.post("/api/v1/catalog/stores", json={"name": "A", "slug": "a"}, headers=h)).json()["id"]
    sb = (await client.post("/api/v1/catalog/stores", json={"name": "B", "slug": "b"}, headers=h)).json()["id"]
    await client.put(f"/api/v1/catalog/stores/{sa}/offers/{arroz}", json={"price": 20.0}, headers=h)
    await client.put(f"/api/v1/catalog/stores/{sb}/offers/{arroz}", json={"price": 25.0}, headers=h)
    await client.put(f"/api/v1/catalog/stores/{sa}/offers/{feijao}", json={"price": 12.0}, headers=h)
    await client.put(f"/api/v1/catalog/stores/{sb}/offers/{feijao}", json={"price": 8.0}, headers=h)

    await client.post("/api/v1/auth/register", json={"email": "u2@ef.com", "full_name": "User", "password": "SenhaForte1"})
    ut = (await client.post(LOGIN, json={"email": "u2@ef.com", "password": "SenhaForte1"})).json()["access_token"]
    uh = {"Authorization": f"Bearer {ut}"}
    await client.post("/api/v1/cart/items", json={"product_id": arroz, "quantity": 1}, headers=uh)
    await client.post("/api/v1/cart/items", json={"product_id": feijao, "quantity": 1}, headers=uh)

    opt = (await client.get("/api/v1/cart/optimize", headers=uh)).json()
    assert opt["recommended"] == "split"
    assert opt["split"]["total"] == 28.0
    assert opt["engine"]["method"] == "noor-ilp"
    assert opt["engine"]["optimal"] is True
