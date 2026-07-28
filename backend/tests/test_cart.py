"""Testes do otimizador (RN-018) e do fluxo carrinho -> checkout -> pedidos."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.cart import Cart
from app.models.user import UserRole
from app.services.optimizer_service import plan_purchase

LOGIN = "/api/v1/auth/login"


def _offer(name, price):
    return {"store_name": name, "price": price}


# --------------------------------------------------------------------------- #
# Otimizador — unitários (RN-018)
# --------------------------------------------------------------------------- #
def test_split_recommended_when_savings_above_2pct():
    items = [
        {"product_id": "A", "name": "A", "quantity": 1},
        {"product_id": "B", "name": "B", "quantity": 1},
    ]
    offers = {
        "A": {"s1": _offer("Loja 1", 10), "s2": _offer("Loja 2", 20)},
        "B": {"s1": _offer("Loja 1", 20), "s2": _offer("Loja 2", 8)},
    }
    res = plan_purchase(items, offers)
    assert res["recommended"] == "split"
    assert res["single_store"]["total"] == 28          # melhor loja única (Loja 2)
    assert res["split"]["total"] == 18                  # 10 + 8
    assert res["split"]["store_count"] == 2
    assert res["savings"] == 10.0
    assert res["meets_min_savings"] is True


def test_single_preferred_when_split_savings_marginal():
    items = [
        {"product_id": "A", "name": "A", "quantity": 1},
        {"product_id": "B", "name": "B", "quantity": 1},
    ]
    offers = {
        "A": {"s1": _offer("Loja 1", 10.0), "s2": _offer("Loja 2", 9.9)},
        "B": {"s1": _offer("Loja 1", 10.0), "s2": _offer("Loja 2", 10.1)},
    }
    res = plan_purchase(items, offers)
    # economia possível ~0.5% < 2% -> conveniência vence
    assert res["recommended"] == "single"
    assert res["meets_min_savings"] is False


def test_split_forced_when_no_single_store_has_everything():
    items = [
        {"product_id": "A", "name": "A", "quantity": 1},
        {"product_id": "B", "name": "B", "quantity": 1},
    ]
    offers = {
        "A": {"s1": _offer("Loja 1", 10)},
        "B": {"s2": _offer("Loja 2", 8)},
    }
    res = plan_purchase(items, offers)
    assert res["fulfillable"] is True
    assert res["single_store"] is None
    assert res["recommended"] == "split"
    assert res["split"]["store_count"] == 2


def test_respects_max_three_stores():
    items = [{"product_id": p, "name": p, "quantity": 1} for p in "ABCD"]
    # cada item é mais barato numa loja própria, mas todos existem na loja comum s0
    offers = {}
    for i, p in enumerate("ABCD", start=1):
        offers[p] = {"s0": _offer("Comum", 2.0), f"s{i}": _offer(f"Loja {i}", 1.0)}
    res = plan_purchase(items, offers)
    assert res["fulfillable"] is True
    chosen = res["split"] or res["single_store"]
    assert chosen["store_count"] <= 3


# --------------------------------------------------------------------------- #
# Integração — fluxo completo
# --------------------------------------------------------------------------- #
async def _setup_catalog(client, make_privileged_user):
    await make_privileged_user("adm@ef.com", "AdminPass1", UserRole.ADMIN)
    tok = (await client.post(LOGIN, json={"email": "adm@ef.com", "password": "AdminPass1"})).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    cat = (await client.post("/api/v1/catalog/categories", json={"name": "Mercearia", "slug": "merc"}, headers=h)).json()["id"]
    arroz = (await client.post("/api/v1/catalog/products", json={"name": "Arroz 5kg", "package_size": 5, "package_unit": "kg", "category_id": cat}, headers=h)).json()["id"]
    feijao = (await client.post("/api/v1/catalog/products", json={"name": "Feijão 1kg", "package_size": 1, "package_unit": "kg", "category_id": cat}, headers=h)).json()["id"]
    sa = (await client.post("/api/v1/catalog/stores", json={"name": "Loja A", "slug": "a"}, headers=h)).json()["id"]
    sb = (await client.post("/api/v1/catalog/stores", json={"name": "Loja B", "slug": "b"}, headers=h)).json()["id"]
    # Arroz mais barato em A; Feijão mais barato em B -> split compensa
    await client.put(f"/api/v1/catalog/stores/{sa}/offers/{arroz}", json={"price": 20.0}, headers=h)
    await client.put(f"/api/v1/catalog/stores/{sb}/offers/{arroz}", json={"price": 25.0}, headers=h)
    await client.put(f"/api/v1/catalog/stores/{sa}/offers/{feijao}", json={"price": 12.0}, headers=h)
    await client.put(f"/api/v1/catalog/stores/{sb}/offers/{feijao}", json={"price": 8.0}, headers=h)
    return arroz, feijao


async def _consumer(client):
    await client.post("/api/v1/auth/register", json={"email": "u@ef.com", "full_name": "User", "password": "SenhaForte1"})
    tok = (await client.post(LOGIN, json={"email": "u@ef.com", "password": "SenhaForte1"})).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


async def test_full_cart_checkout_flow(client, make_privileged_user):
    arroz, feijao = await _setup_catalog(client, make_privileged_user)
    h = await _consumer(client)

    await client.post("/api/v1/cart/items", json={"product_id": arroz, "quantity": 1}, headers=h)
    cart = (await client.post("/api/v1/cart/items", json={"product_id": feijao, "quantity": 1}, headers=h)).json()
    assert cart["item_count"] == 2
    assert all(i["available"] for i in cart["items"])

    opt = (await client.get("/api/v1/cart/optimize", headers=h)).json()
    assert opt["recommended"] == "split"
    assert opt["single_store"]["total"] == 32.0   # melhor loja única (Loja A)
    assert opt["split"]["total"] == 28.0           # 20 (A) + 8 (B)
    assert opt["savings"] == 4.0

    order = (await client.post("/api/v1/cart/checkout", json={"strategy": "recommended"}, headers=h)).json()
    assert order["code"].startswith("EF-")
    assert order["store_count"] == 2
    assert order["savings"] == 4.0
    assert order["total"] == 28.0
    assert len(order["items"]) == 2

    # carrinho é renovado após checkout
    fresh = (await client.get("/api/v1/cart", headers=h)).json()
    assert fresh["item_count"] == 0

    # histórico e detalhe
    orders = (await client.get("/api/v1/orders", headers=h)).json()
    assert len(orders) == 1
    detail = (await client.get(f"/api/v1/orders/{orders[0]['id']}", headers=h)).json()
    assert {i["store_name"] for i in detail["items"]} == {"Loja A", "Loja B"}


async def test_cart_expiry_creates_fresh_cart(client, make_privileged_user, db):
    arroz, _ = await _setup_catalog(client, make_privileged_user)
    h = await _consumer(client)
    await client.post("/api/v1/cart/items", json={"product_id": arroz, "quantity": 1}, headers=h)

    # expira o carrinho manualmente (RN-008)
    cart = (await db.execute(select(Cart))).scalars().first()
    cart.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await db.commit()

    fresh = (await client.get("/api/v1/cart", headers=h)).json()
    assert fresh["item_count"] == 0
