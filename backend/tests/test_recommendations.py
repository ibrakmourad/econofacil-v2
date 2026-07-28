"""Testes das recomendações da Noor V2 (RN-023).

Cobre coocorrência ("quem comprou X também comprou") e sugestões de
recompra ("você costuma comprar"), ambas calculadas a partir do histórico
real de pedidos.
"""
from app.models.user import UserRole

LOGIN = "/api/v1/auth/login"


async def _admin(client, make_privileged_user, email="noor_adm@ef.com"):
    await make_privileged_user(email, "AdminPass1", UserRole.ADMIN)
    tok = (await client.post(LOGIN, json={"email": email, "password": "AdminPass1"})).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


async def _consumer(client, email="noor_cli@ef.com"):
    await client.post("/api/v1/auth/register", json={"email": email, "full_name": "Cli", "password": "SenhaForte1"})
    tok = (await client.post(LOGIN, json={"email": email, "password": "SenhaForte1"})).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


async def _catalog(client, h):
    store = (await client.post("/api/v1/catalog/stores", json={"name": "Loja Noor", "slug": "noor"}, headers=h)).json()["id"]
    products = {}
    for name in ["Arroz", "Feijão", "Macarrão", "Sabão"]:
        pid = (await client.post("/api/v1/catalog/products", json={"name": name, "package_size": 1, "package_unit": "kg"}, headers=h)).json()["id"]
        await client.put(f"/api/v1/catalog/stores/{store}/offers/{pid}", json={"price": 10.0}, headers=h)
        products[name] = pid
    return products


async def _buy(client, headers, product_ids):
    for pid in product_ids:
        await client.post("/api/v1/cart/items", json={"product_id": pid, "quantity": 1}, headers=headers)
    return (await client.post("/api/v1/cart/checkout", json={"strategy": "single", "payment_method": "econopay"}, headers=headers)).json()


async def test_related_products_reflects_co_purchases(client, make_privileged_user):
    h = await _admin(client, make_privileged_user)
    products = await _catalog(client, h)

    # três clientes compram Arroz + Feijão juntos; só um também leva Macarrão
    for email in ["noor_a@ef.com", "noor_b@ef.com", "noor_c@ef.com"]:
        ch = await _consumer(client, email)
        await _buy(client, ch, [products["Arroz"], products["Feijão"]])

    ch2 = await _consumer(client, "noor_d@ef.com")
    await _buy(client, ch2, [products["Arroz"], products["Macarrão"]])

    related = (await client.get(f"/api/v1/noor/recommendations/related/{products['Arroz']}")).json()
    names_in_order = [r["name"] for r in related]
    assert names_in_order[0] == "Feijão"   # maior coocorrência (3 pedidos)
    feijao = next(r for r in related if r["name"] == "Feijão")
    assert feijao["co_purchase_count"] == 3
    macarrao = next(r for r in related if r["name"] == "Macarrão")
    assert macarrao["co_purchase_count"] == 1
    assert all(r["name"] != "Sabão" for r in related)   # nunca comprado junto


async def test_related_products_excludes_cancelled_orders(client, make_privileged_user, db):
    import uuid
    from sqlalchemy import select
    from app.models.order import Order, OrderStatus

    h = await _admin(client, make_privileged_user, "noor_cancel_adm@ef.com")
    products = await _catalog(client, h)
    ch = await _consumer(client, "noor_cancel_cli@ef.com")
    order = await _buy(client, ch, [products["Arroz"], products["Sabão"]])

    o = await db.get(Order, uuid.UUID(order["id"]))
    o.status = OrderStatus.CANCELLED
    await db.commit()

    related = (await client.get(f"/api/v1/noor/recommendations/related/{products['Arroz']}")).json()
    assert all(r["name"] != "Sabão" for r in related)


async def test_reorder_suggestions_need_at_least_two_purchases(client, make_privileged_user):
    h = await _admin(client, make_privileged_user, "noor_reorder_adm@ef.com")
    products = await _catalog(client, h)
    ch = await _consumer(client, "noor_reorder_cli@ef.com")

    # Arroz comprado 2x, Feijão só 1x
    await _buy(client, ch, [products["Arroz"]])
    await _buy(client, ch, [products["Arroz"]])
    await _buy(client, ch, [products["Feijão"]])

    suggestions = (await client.get("/api/v1/noor/recommendations/reorder", headers=ch)).json()
    names = {s["name"] for s in suggestions}
    assert "Arroz" in names
    assert "Feijão" not in names   # só 1 compra, não vira sugestão

    arroz = next(s for s in suggestions if s["name"] == "Arroz")
    assert arroz["times_bought"] == 2


async def test_reorder_suggestions_exclude_items_already_in_cart(client, make_privileged_user):
    h = await _admin(client, make_privileged_user, "noor_incart_adm@ef.com")
    products = await _catalog(client, h)
    ch = await _consumer(client, "noor_incart_cli@ef.com")

    await _buy(client, ch, [products["Arroz"]])
    await _buy(client, ch, [products["Arroz"]])

    # o usuário já colocou Arroz de novo no carrinho ativo
    await client.post("/api/v1/cart/items", json={"product_id": products["Arroz"], "quantity": 1}, headers=ch)

    suggestions = (await client.get("/api/v1/noor/recommendations/reorder", headers=ch)).json()
    assert all(s["name"] != "Arroz" for s in suggestions)


async def test_reorder_suggestions_are_private_per_user(client, make_privileged_user):
    h = await _admin(client, make_privileged_user, "noor_private_adm@ef.com")
    products = await _catalog(client, h)
    ch_a = await _consumer(client, "noor_private_a@ef.com")
    ch_b = await _consumer(client, "noor_private_b@ef.com")

    await _buy(client, ch_a, [products["Arroz"]])
    await _buy(client, ch_a, [products["Arroz"]])

    suggestions_b = (await client.get("/api/v1/noor/recommendations/reorder", headers=ch_b)).json()
    assert suggestions_b == []


async def test_noor_status_reports_recommender_version(client):
    status = (await client.get("/api/v1/noor/status")).json()
    assert status["recommender_version"] == "noor-recommender-1.0.0"
