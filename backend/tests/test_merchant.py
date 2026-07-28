"""Testes do Portal do Comerciante."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.promotion import Promotion
from app.models.user import UserRole

LOGIN = "/api/v1/auth/login"


async def _merchant(client, make_privileged_user, email):
    await make_privileged_user(email, "MerchPass1", UserRole.MERCHANT)
    tok = (await client.post(LOGIN, json={"email": email, "password": "MerchPass1"})).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


async def _consumer(client, email="cli@ef.com"):
    await client.post("/api/v1/auth/register", json={"email": email, "full_name": "Cli", "password": "SenhaForte1"})
    tok = (await client.post(LOGIN, json={"email": email, "password": "SenhaForte1"})).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


async def _store_with_products(client, h, slug):
    store = (await client.post("/api/v1/catalog/stores", json={"name": f"Loja {slug}", "slug": slug}, headers=h)).json()["id"]
    p1 = (await client.post("/api/v1/catalog/products", json={"name": "Arroz 5kg", "package_size": 5, "package_unit": "kg"}, headers=h)).json()["id"]
    p2 = (await client.post("/api/v1/catalog/products", json={"name": "Feijão 1kg", "package_size": 1, "package_unit": "kg"}, headers=h)).json()["id"]
    await client.put(f"/api/v1/catalog/stores/{store}/offers/{p1}", json={"price": 20.0, "stock_quantity": 40}, headers=h)
    await client.put(f"/api/v1/catalog/stores/{store}/offers/{p2}", json={"price": 8.0, "stock_quantity": 60}, headers=h)
    return store, p1, p2


async def test_my_stores_and_inventory(client, make_privileged_user):
    h = await _merchant(client, make_privileged_user, "m1@ef.com")
    store, p1, p2 = await _store_with_products(client, h, "a")

    stores = (await client.get("/api/v1/merchant/stores", headers=h)).json()
    assert len(stores) == 1 and stores[0]["id"] == store

    inv = (await client.get(f"/api/v1/merchant/stores/{store}/inventory", headers=h)).json()
    assert len(inv) == 2
    arroz = next(r for r in inv if r["product_name"] == "Arroz 5kg")
    assert arroz["price"] == 20.0 and arroz["stock_quantity"] == 40


async def test_ownership_isolation(client, make_privileged_user):
    ha = await _merchant(client, make_privileged_user, "a@ef.com")
    hb = await _merchant(client, make_privileged_user, "b@ef.com")
    store, p1, _ = await _store_with_products(client, ha, "owned")

    # B não vê o inventário da loja de A
    assert (await client.get(f"/api/v1/merchant/stores/{store}/inventory", headers=hb)).status_code == 403
    # B não consegue alterar oferta na loja de A (brecha de autorização fechada)
    r = await client.put(f"/api/v1/catalog/stores/{store}/offers/{p1}", json={"price": 1.0}, headers=hb)
    assert r.status_code == 403


async def test_promotion_apply_and_end(client, make_privileged_user):
    h = await _merchant(client, make_privileged_user, "promo@ef.com")
    store, p1, _ = await _store_with_products(client, h, "promo")
    ends = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()

    promo = await client.post(
        f"/api/v1/merchant/stores/{store}/promotions",
        json={"product_id": p1, "promo_price": 14.9, "ends_at": ends}, headers=h,
    )
    assert promo.status_code == 201
    promo_id = promo.json()["id"]

    # o PDP passa a refletir o preço promocional, com o antigo riscado
    pdp = (await client.get(f"/api/v1/catalog/products/{p1}")).json()
    assert pdp["best_unit_price"] == 14.9 / 5      # R$/kg do promocional
    assert pdp["offers"][0]["price"] == 14.9
    assert pdp["offers"][0]["original_price"] == 20.0

    # promo com preço maior que o atual é rejeitada
    bad = await client.post(
        f"/api/v1/merchant/stores/{store}/promotions",
        json={"product_id": p1, "promo_price": 99.0, "ends_at": ends}, headers=h,
    )
    assert bad.status_code == 422

    # encerrar restaura o preço-base
    ended = await client.request("DELETE", f"/api/v1/merchant/promotions/{promo_id}", headers=h)
    assert ended.json()["status"] == "ended"
    pdp2 = (await client.get(f"/api/v1/catalog/products/{p1}")).json()
    assert pdp2["offers"][0]["price"] == 20.0


async def test_promotion_auto_expires_on_read(client, make_privileged_user, db):
    h = await _merchant(client, make_privileged_user, "exp@ef.com")
    store, p1, _ = await _store_with_products(client, h, "exp")
    ends = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    await client.post(
        f"/api/v1/merchant/stores/{store}/promotions",
        json={"product_id": p1, "promo_price": 15.0, "ends_at": ends}, headers=h,
    )
    # força o vencimento
    promo = (await db.execute(select(Promotion))).scalars().first()
    promo.ends_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await db.commit()

    listed = (await client.get(f"/api/v1/merchant/stores/{store}/promotions", headers=h)).json()
    assert listed[0]["status"] == "ended"
    pdp = (await client.get(f"/api/v1/catalog/products/{p1}")).json()
    assert pdp["offers"][0]["price"] == 20.0   # preço-base restaurado


async def test_merchant_orders_and_report(client, make_privileged_user):
    h = await _merchant(client, make_privileged_user, "ord@ef.com")
    store, p1, p2 = await _store_with_products(client, h, "ord")
    ch = await _consumer(client)

    await client.post("/api/v1/cart/items", json={"product_id": p1, "quantity": 2}, headers=ch)
    await client.post("/api/v1/cart/items", json={"product_id": p2, "quantity": 1}, headers=ch)
    order = (await client.post("/api/v1/cart/checkout", json={"strategy": "single"}, headers=ch)).json()
    assert order["total"] == 48.0   # 2*20 + 1*8

    orders = (await client.get("/api/v1/merchant/orders", headers=h)).json()
    assert len(orders) == 1
    assert orders[0]["store_subtotal"] == 48.0
    assert len(orders[0]["items"]) == 2

    upd = await client.patch(
        f"/api/v1/merchant/orders/{orders[0]['order_id']}/status",
        json={"status": "separating"}, headers=h,
    )
    assert upd.json()["status"] == "separating"

    report = (await client.get(f"/api/v1/merchant/stores/{store}/report", headers=h)).json()
    assert report["orders_count"] == 1
    assert report["revenue"] == 48.0
    assert report["units_sold"] == 3
    assert report["top_products"][0]["product_name"] == "Arroz 5kg"  # 2 unidades


async def test_consumer_blocked_from_portal(client):
    ch = await _consumer(client, "blocked@ef.com")
    assert (await client.get("/api/v1/merchant/stores", headers=ch)).status_code == 403
