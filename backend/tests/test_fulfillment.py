"""Testes de fulfillment por loja (RN-019).

Um pedido split entre lojas deve permitir que cada comerciante evolua o
status da sua própria loja de forma independente, com o status geral do
pedido derivado (a loja mais atrasada) e só chegando a "delivered" quando
todas as lojas tiverem entregado.
"""
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


async def _split_order(client, ha, hb):
    """Monta um carrinho cujo split favorece Loja A (Arroz) + Loja B (Feijão)."""
    arroz = (await client.post("/api/v1/catalog/products", json={"name": "Arroz 5kg", "package_size": 5, "package_unit": "kg"}, headers=ha)).json()["id"]
    feijao = (await client.post("/api/v1/catalog/products", json={"name": "Feijão 1kg", "package_size": 1, "package_unit": "kg"}, headers=ha)).json()["id"]
    sa = (await client.post("/api/v1/catalog/stores", json={"name": "Loja A", "slug": "fa"}, headers=ha)).json()["id"]
    sb = (await client.post("/api/v1/catalog/stores", json={"name": "Loja B", "slug": "fb"}, headers=hb)).json()["id"]
    await client.put(f"/api/v1/catalog/stores/{sa}/offers/{arroz}", json={"price": 20.0}, headers=ha)
    await client.put(f"/api/v1/catalog/stores/{sb}/offers/{arroz}", json={"price": 25.0}, headers=hb)
    await client.put(f"/api/v1/catalog/stores/{sa}/offers/{feijao}", json={"price": 12.0}, headers=ha)
    await client.put(f"/api/v1/catalog/stores/{sb}/offers/{feijao}", json={"price": 8.0}, headers=hb)
    return sa, sb


async def test_checkout_creates_one_fulfillment_per_store(client, make_privileged_user):
    ha = await _merchant(client, make_privileged_user, "fa@ef.com")
    hb = await _merchant(client, make_privileged_user, "fb@ef.com")
    await _split_order(client, ha, hb)
    ch = await _consumer(client)

    products = (await client.get("/api/v1/catalog/products")).json()["items"]
    for p in products:
        await client.post("/api/v1/cart/items", json={"product_id": p["id"], "quantity": 1}, headers=ch)

    order = (await client.post("/api/v1/cart/checkout", json={"strategy": "recommended", "payment_method": "econopay"}, headers=ch)).json()
    assert order["store_count"] == 2
    assert {f["status"] for f in order["fulfillments"]} == {"placed"}
    assert {f["store_name"] for f in order["fulfillments"]} == {"Loja A", "Loja B"}
    assert order["status"] == "placed"


async def test_pix_order_fulfillments_start_awaiting_payment(client, make_privileged_user):
    ha = await _merchant(client, make_privileged_user, "pa@ef.com")
    hb = await _merchant(client, make_privileged_user, "pb@ef.com")
    await _split_order(client, ha, hb)
    ch = await _consumer(client, "pixcli@ef.com")
    products = (await client.get("/api/v1/catalog/products", headers=ch)).json()["items"]
    for p in products:
        await client.post("/api/v1/cart/items", json={"product_id": p["id"], "quantity": 1}, headers=ch)

    order = (await client.post("/api/v1/cart/checkout", json={"strategy": "recommended", "payment_method": "pix"}, headers=ch)).json()
    assert order["status"] == "awaiting_payment"
    assert {f["status"] for f in order["fulfillments"]} == {"awaiting_payment"}


async def test_each_merchant_advances_only_their_store(client, make_privileged_user):
    ha = await _merchant(client, make_privileged_user, "ga@ef.com")
    hb = await _merchant(client, make_privileged_user, "gb@ef.com")
    await _split_order(client, ha, hb)
    ch = await _consumer(client, "gcli@ef.com")
    products = (await client.get("/api/v1/catalog/products", headers=ch)).json()["items"]
    for p in products:
        await client.post("/api/v1/cart/items", json={"product_id": p["id"], "quantity": 1}, headers=ch)

    order = (await client.post("/api/v1/cart/checkout", json={"strategy": "recommended", "payment_method": "econopay"}, headers=ch)).json()

    orders_a = (await client.get("/api/v1/merchant/orders", headers=ha)).json()
    assert len(orders_a) == 1
    row_a = orders_a[0]
    assert row_a["store_name"] == "Loja A"
    assert row_a["status"] == "placed"

    # Loja A avança para "separating"; Loja B não é afetada
    upd = await client.patch(
        f"/api/v1/merchant/orders/{row_a['order_id']}/status",
        json={"status": "separating"}, headers=ha,
    )
    assert upd.status_code == 200
    assert upd.json()["status"] == "separating"
    assert upd.json()["store_name"] == "Loja A"

    orders_b = (await client.get("/api/v1/merchant/orders", headers=hb)).json()
    assert orders_b[0]["status"] == "placed"   # Loja B não mudou

    # o status geral do pedido reflete a loja mais atrasada (Loja B = placed)
    detail = (await client.get(f"/api/v1/orders/{order['id']}", headers=ch)).json()
    assert detail["status"] == "placed"
    by_store = {f["store_name"]: f["status"] for f in detail["fulfillments"]}
    assert by_store["Loja A"] == "separating"
    assert by_store["Loja B"] == "placed"

    # Loja B também avança; agora as duas em "separating" -> pedido geral idem
    await client.patch(
        f"/api/v1/merchant/orders/{orders_b[0]['order_id']}/status",
        json={"status": "separating"}, headers=hb,
    )
    detail2 = (await client.get(f"/api/v1/orders/{order['id']}", headers=ch)).json()
    assert detail2["status"] == "separating"


async def test_order_only_delivered_when_all_stores_delivered(client, make_privileged_user):
    ha = await _merchant(client, make_privileged_user, "da@ef.com")
    hb = await _merchant(client, make_privileged_user, "db@ef.com")
    await _split_order(client, ha, hb)
    ch = await _consumer(client, "dcli@ef.com")
    products = (await client.get("/api/v1/catalog/products", headers=ch)).json()["items"]
    for p in products:
        await client.post("/api/v1/cart/items", json={"product_id": p["id"], "quantity": 1}, headers=ch)
    order = (await client.post("/api/v1/cart/checkout", json={"strategy": "recommended", "payment_method": "econopay"}, headers=ch)).json()

    row_a = (await client.get("/api/v1/merchant/orders", headers=ha)).json()[0]
    row_b = (await client.get("/api/v1/merchant/orders", headers=hb)).json()[0]

    for status in ("separating", "on_the_way", "delivered"):
        await client.patch(f"/api/v1/merchant/orders/{row_a['order_id']}/status", json={"status": status}, headers=ha)
        detail = (await client.get(f"/api/v1/orders/{order['id']}", headers=ch)).json()
        assert detail["status"] != "delivered"   # Loja B ainda não entregou

    for status in ("separating", "on_the_way", "delivered"):
        await client.patch(f"/api/v1/merchant/orders/{row_b['order_id']}/status", json={"status": status}, headers=hb)

    detail = (await client.get(f"/api/v1/orders/{order['id']}", headers=ch)).json()
    assert detail["status"] == "delivered"
    assert all(f["status"] == "delivered" for f in detail["fulfillments"])


async def test_ambiguous_store_requires_explicit_store_id(client, make_privileged_user):
    """Um comerciante que possui as duas lojas do split precisa informar store_id."""
    h = await _merchant(client, make_privileged_user, "both@ef.com")
    await _split_order(client, h, h)  # o mesmo comerciante é dono de A e B
    ch = await _consumer(client, "bothcli@ef.com")
    products = (await client.get("/api/v1/catalog/products", headers=ch)).json()["items"]
    for p in products:
        await client.post("/api/v1/cart/items", json={"product_id": p["id"], "quantity": 1}, headers=ch)
    order = (await client.post("/api/v1/cart/checkout", json={"strategy": "recommended", "payment_method": "econopay"}, headers=ch)).json()

    rows = (await client.get("/api/v1/merchant/orders", headers=h)).json()
    assert len(rows) == 2

    ambiguous = await client.patch(
        f"/api/v1/merchant/orders/{order['id']}/status", json={"status": "separating"}, headers=h,
    )
    assert ambiguous.status_code == 422

    explicit = await client.patch(
        f"/api/v1/merchant/orders/{order['id']}/status",
        json={"status": "separating", "store_id": rows[0]["store_id"]}, headers=h,
    )
    assert explicit.status_code == 200
    assert explicit.json()["store_id"] == rows[0]["store_id"]

    rows_after = (await client.get("/api/v1/merchant/orders", headers=h)).json()
    statuses = {r["store_id"]: r["status"] for r in rows_after}
    assert statuses[rows[0]["store_id"]] == "separating"
    assert statuses[rows[1]["store_id"]] == "placed"
