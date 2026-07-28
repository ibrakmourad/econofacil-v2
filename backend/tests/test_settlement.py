"""Testes de liquidação Pix por loja (RN-022).

Um pedido split entre lojas gera uma cobrança Pix **por loja** (valor,
BR Code, QR e txid próprios), na chave Pix da própria loja quando
configurada — em vez de uma única cobrança para o pedido inteiro.
"""
from datetime import datetime, timedelta, timezone

from app.models.user import UserRole
from app.payments import pix

LOGIN = "/api/v1/auth/login"


async def _merchant(client, make_privileged_user, email):
    await make_privileged_user(email, "MerchPass1", UserRole.MERCHANT)
    tok = (await client.post(LOGIN, json={"email": email, "password": "MerchPass1"})).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


async def _consumer(client, email="settlecli@ef.com"):
    await client.post("/api/v1/auth/register", json={"email": email, "full_name": "Cli", "password": "SenhaForte1"})
    tok = (await client.post(LOGIN, json={"email": email, "password": "SenhaForte1"})).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


async def _split_setup(client, ha, hb, pix_key_a=None, pix_key_b=None):
    """Arroz mais barato na Loja A; Feijão mais barato na Loja B -> split compensa."""
    arroz = (await client.post("/api/v1/catalog/products", json={"name": "Arroz 5kg", "package_size": 5, "package_unit": "kg"}, headers=ha)).json()["id"]
    feijao = (await client.post("/api/v1/catalog/products", json={"name": "Feijão 1kg", "package_size": 1, "package_unit": "kg"}, headers=ha)).json()["id"]
    store_a_payload = {"name": "Loja SA", "slug": "sa"}
    if pix_key_a:
        store_a_payload["pix_key"] = pix_key_a
    store_b_payload = {"name": "Loja SB", "slug": "sb"}
    if pix_key_b:
        store_b_payload["pix_key"] = pix_key_b
    sa = (await client.post("/api/v1/catalog/stores", json=store_a_payload, headers=ha)).json()["id"]
    sb = (await client.post("/api/v1/catalog/stores", json=store_b_payload, headers=hb)).json()["id"]
    await client.put(f"/api/v1/catalog/stores/{sa}/offers/{arroz}", json={"price": 20.0}, headers=ha)
    await client.put(f"/api/v1/catalog/stores/{sb}/offers/{arroz}", json={"price": 25.0}, headers=hb)
    await client.put(f"/api/v1/catalog/stores/{sa}/offers/{feijao}", json={"price": 12.0}, headers=ha)
    await client.put(f"/api/v1/catalog/stores/{sb}/offers/{feijao}", json={"price": 8.0}, headers=hb)
    return sa, sb, arroz, feijao


async def _checkout_split(client, ha, hb, ch, payment_method="pix", pix_key_a=None, pix_key_b=None):
    sa, sb, arroz, feijao = await _split_setup(client, ha, hb, pix_key_a, pix_key_b)
    await client.post("/api/v1/cart/items", json={"product_id": arroz, "quantity": 1}, headers=ch)
    await client.post("/api/v1/cart/items", json={"product_id": feijao, "quantity": 1}, headers=ch)
    order = (await client.post(
        "/api/v1/cart/checkout",
        json={"strategy": "recommended", "payment_method": payment_method},
        headers=ch,
    )).json()
    return order, sa, sb


async def test_split_order_generates_one_pix_charge_per_store(client, make_privileged_user):
    ha = await _merchant(client, make_privileged_user, "sa1@ef.com")
    hb = await _merchant(client, make_privileged_user, "sb1@ef.com")
    ch = await _consumer(client, "settle1@ef.com")

    order, sa, sb = await _checkout_split(client, ha, hb, ch)

    assert order["store_count"] == 2
    assert len(order["payments"]) == 2
    assert order["status"] == "awaiting_payment"

    by_store = {p["store_id"]: p for p in order["payments"]}
    assert by_store[sa]["amount"] == 20.0   # subtotal só da Loja A (arroz)
    assert by_store[sb]["amount"] == 8.0    # subtotal só da Loja B (feijão)
    assert by_store[sa]["store_name"] == "Loja SA"
    assert by_store[sb]["store_name"] == "Loja SB"

    # cada loja tem seu próprio txid e BR Code válido, únicos entre si
    txid_a = by_store[sa]["pix"]["txid"]
    txid_b = by_store[sb]["pix"]["txid"]
    assert txid_a != txid_b
    assert pix.verify_payload(by_store[sa]["pix"]["br_code"]) is True
    assert pix.verify_payload(by_store[sb]["pix"]["br_code"]) is True


async def test_store_pix_key_used_when_configured(client, make_privileged_user):
    ha = await _merchant(client, make_privileged_user, "sa2@ef.com")
    hb = await _merchant(client, make_privileged_user, "sb2@ef.com")
    ch = await _consumer(client, "settle2@ef.com")

    order, sa, sb = await _checkout_split(
        client, ha, hb, ch,
        pix_key_a="lojaA@pix.com.br",   # Loja B fica sem chave própria -> cai na da plataforma
    )
    by_store = {p["store_id"]: p for p in order["payments"]}

    # a chave usada vira o campo "01" dentro do Merchant Account Information (26);
    # o jeito simples de verificar é conferir que o payload da Loja A contém a chave dela.
    assert "lojaA@pix.com.br" in by_store[sa]["pix"]["br_code"]
    assert "lojaA@pix.com.br" not in by_store[sb]["pix"]["br_code"]


async def test_confirming_one_store_payment_only_advances_that_store(client, make_privileged_user):
    ha = await _merchant(client, make_privileged_user, "sa3@ef.com")
    hb = await _merchant(client, make_privileged_user, "sb3@ef.com")
    ch = await _consumer(client, "settle3@ef.com")

    order, sa, sb = await _checkout_split(client, ha, hb, ch)
    by_store = {p["store_id"]: p for p in order["payments"]}
    txid_a = by_store[sa]["pix"]["txid"]

    from app.core.config import settings

    ok = await client.post(
        "/api/v1/payments/pix/webhook",
        json={"txid": txid_a, "event": "payment.confirmed"},
        headers={"X-Webhook-Token": settings.PIX_WEBHOOK_SECRET},
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "paid"

    detail = (await client.get(f"/api/v1/orders/{order['id']}", headers=ch)).json()
    # loja A paga -> fulfillment dela avança; loja B ainda aguardando -> status geral
    # continua refletindo a mais atrasada (RN-019)
    by_fulfillment = {f["store_id"]: f["status"] for f in detail["fulfillments"]}
    assert by_fulfillment[sa] == "placed"
    assert by_fulfillment[sb] == "awaiting_payment"
    assert detail["status"] == "awaiting_payment"

    by_payment = {p["store_id"]: p["status"] for p in detail["payments"]}
    assert by_payment[sa] == "paid"
    assert by_payment[sb] == "pending"


async def test_expired_store_payment_cancels_only_that_store(client, make_privileged_user, db):
    from sqlalchemy import select
    from app.models.payment import Payment

    ha = await _merchant(client, make_privileged_user, "sa4@ef.com")
    hb = await _merchant(client, make_privileged_user, "sb4@ef.com")
    await make_privileged_user("settleadm@ef.com", "AdminPass1", UserRole.ADMIN)
    admin_tok = (await client.post(LOGIN, json={"email": "settleadm@ef.com", "password": "AdminPass1"})).json()["access_token"]
    admin_h = {"Authorization": f"Bearer {admin_tok}"}
    ch = await _consumer(client, "settle4@ef.com")

    order, sa, sb = await _checkout_split(client, ha, hb, ch)
    by_store = {p["store_id"]: p for p in order["payments"]}

    from app.core.config import settings
    # loja A paga normalmente
    ok = await client.post(
        "/api/v1/payments/pix/webhook",
        json={"txid": by_store[sa]["pix"]["txid"], "event": "payment.confirmed"},
        headers={"X-Webhook-Token": settings.PIX_WEBHOOK_SECRET},
    )
    assert ok.status_code == 200

    # a cobrança da loja B vence sem confirmação
    payments = (await db.execute(select(Payment))).scalars().all()
    payment_b = next(p for p in payments if str(p.store_id) == sb)
    payment_b.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await db.commit()

    result = (await client.post("/api/v1/admin/expirations/run", headers=admin_h)).json()
    assert result["pix_charges_expired"] == 1

    detail = (await client.get(f"/api/v1/orders/{order['id']}", headers=ch)).json()
    by_fulfillment = {f["store_id"]: f["status"] for f in detail["fulfillments"]}
    assert by_fulfillment[sa] == "placed"      # não foi afetada
    assert by_fulfillment[sb] == "cancelled"   # só ela venceu
    # status geral ignora a cancelada e reflete a loja ativa mais atrasada
    assert detail["status"] == "placed"


async def test_econopay_split_settles_all_stores_instantly(client, make_privileged_user):
    ha = await _merchant(client, make_privileged_user, "sa5@ef.com")
    hb = await _merchant(client, make_privileged_user, "sb5@ef.com")
    ch = await _consumer(client, "settle5@ef.com")

    order, sa, sb = await _checkout_split(client, ha, hb, ch, payment_method="econopay")
    assert order["status"] == "placed"
    assert all(p["status"] == "paid" for p in order["payments"])
    assert all(p["pix"] is None for p in order["payments"])
    assert all(f["status"] == "placed" for f in order["fulfillments"])


async def test_single_store_order_still_generates_exactly_one_payment(client, make_privileged_user):
    h = await _merchant(client, make_privileged_user, "single@ef.com")
    prod = (await client.post("/api/v1/catalog/products", json={"name": "Sabonete", "package_size": 90, "package_unit": "g"}, headers=h)).json()["id"]
    store = (await client.post("/api/v1/catalog/stores", json={"name": "Loja Única", "slug": "unica"}, headers=h)).json()["id"]
    await client.put(f"/api/v1/catalog/stores/{store}/offers/{prod}", json={"price": 3.5}, headers=h)

    ch = await _consumer(client, "single_cli@ef.com")
    await client.post("/api/v1/cart/items", json={"product_id": prod, "quantity": 2}, headers=ch)
    order = (await client.post("/api/v1/cart/checkout", json={"strategy": "single", "payment_method": "pix"}, headers=ch)).json()

    assert len(order["payments"]) == 1
    assert order["payments"][0]["amount"] == 7.0
