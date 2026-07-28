"""Testes de pagamento (PIX, EconoPay) e do webhook de confirmação."""
from app.core.config import settings
from app.models.user import UserRole
from app.payments import pix

LOGIN = "/api/v1/auth/login"


# --------------------------------------------------------------------------- #
# Unitários — BR Code Pix
# --------------------------------------------------------------------------- #
def test_pix_payload_is_valid_and_structured():
    payload = pix.build_pix_payload(
        key="pagamentos@econofacil.com.br",
        merchant_name="EconoFácil",
        merchant_city="São Paulo",
        amount=71.70,
        txid="EF20492",
    )
    assert payload.startswith("000201")            # Payload Format Indicator
    assert "br.gov.bcb.pix" in payload
    assert "5303986" in payload                     # moeda BRL
    assert "540571.70" in payload                   # valor
    assert "5802BR" in payload                      # país
    assert pix.verify_payload(payload) is True      # CRC confere


def test_pix_crc_detects_tampering():
    payload = pix.build_pix_payload(
        key="x@y.com", merchant_name="Loja", merchant_city="Cidade",
        amount=10.0, txid="ABC",
    )
    tampered = payload[:-6] + "00" + payload[-4:]
    assert pix.verify_payload(tampered) is False


def test_qr_svg_generated():
    svg = pix.build_qr_svg("teste")
    assert svg.startswith("<svg") and "</svg>" in svg


# --------------------------------------------------------------------------- #
# Integração
# --------------------------------------------------------------------------- #
async def _setup(client, make_privileged_user):
    await make_privileged_user("adm@pay.com", "AdminPass1", UserRole.ADMIN)
    at = (await client.post(LOGIN, json={"email": "adm@pay.com", "password": "AdminPass1"})).json()["access_token"]
    ah = {"Authorization": f"Bearer {at}"}
    prod = (await client.post("/api/v1/catalog/products", json={"name": "Arroz", "package_size": 5, "package_unit": "kg"}, headers=ah)).json()["id"]
    store = (await client.post("/api/v1/catalog/stores", json={"name": "Loja", "slug": "loja"}, headers=ah)).json()["id"]
    await client.put(f"/api/v1/catalog/stores/{store}/offers/{prod}", json={"price": 20.0}, headers=ah)
    await client.post("/api/v1/auth/register", json={"email": "u@pay.com", "full_name": "User", "password": "SenhaForte1"})
    ut = (await client.post(LOGIN, json={"email": "u@pay.com", "password": "SenhaForte1"})).json()["access_token"]
    uh = {"Authorization": f"Bearer {ut}"}
    await client.post("/api/v1/cart/items", json={"product_id": prod, "quantity": 2}, headers=uh)
    return uh


async def test_checkout_pix_creates_pending_charge(client, make_privileged_user):
    uh = await _setup(client, make_privileged_user)
    order = (await client.post("/api/v1/cart/checkout", json={"strategy": "single", "payment_method": "pix"}, headers=uh)).json()

    assert order["status"] == "awaiting_payment"
    assert len(order["payments"]) == 1
    pay = order["payments"][0]
    assert pay["method"] == "pix"
    assert pay["status"] == "pending"
    assert pay["amount"] == 40.0
    assert pix.verify_payload(pay["pix"]["br_code"]) is True
    assert pay["pix"]["qr_svg"].startswith("<svg")


async def test_pix_webhook_confirms_payment(client, make_privileged_user):
    uh = await _setup(client, make_privileged_user)
    order = (await client.post("/api/v1/cart/checkout", json={"strategy": "single"}, headers=uh)).json()
    txid = order["payments"][0]["pix"]["txid"]
    payment_id = order["payments"][0]["id"]

    # token errado é rejeitado
    bad = await client.post("/api/v1/payments/pix/webhook", json={"txid": txid}, headers={"X-Webhook-Token": "errado"})
    assert bad.status_code == 401

    # token correto confirma
    ok = await client.post(
        "/api/v1/payments/pix/webhook",
        json={"txid": txid, "event": "payment.confirmed"},
        headers={"X-Webhook-Token": settings.PIX_WEBHOOK_SECRET},
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "paid"

    # pedido passa a "placed" e o pagamento aparece pago
    detail = (await client.get(f"/api/v1/orders/{order['id']}", headers=uh)).json()
    assert detail["status"] == "placed"
    assert detail["payments"][0]["status"] == "paid"

    pay = (await client.get(f"/api/v1/payments/{payment_id}", headers=uh)).json()
    assert pay["status"] == "paid"


async def test_payment_is_private_to_owner(client, make_privileged_user):
    uh = await _setup(client, make_privileged_user)
    order = (await client.post("/api/v1/cart/checkout", json={"strategy": "single"}, headers=uh)).json()
    pid = order["payments"][0]["id"]

    await client.post("/api/v1/auth/register", json={"email": "intruso@pay.com", "full_name": "Intruso", "password": "SenhaForte1"})
    it = (await client.post(LOGIN, json={"email": "intruso@pay.com", "password": "SenhaForte1"})).json()["access_token"]
    resp = await client.get(f"/api/v1/payments/{pid}", headers={"Authorization": f"Bearer {it}"})
    assert resp.status_code == 404


async def test_econopay_is_instant(client, make_privileged_user):
    uh = await _setup(client, make_privileged_user)
    order = (await client.post("/api/v1/cart/checkout", json={"strategy": "single", "payment_method": "econopay"}, headers=uh)).json()
    assert order["status"] == "placed"
    assert order["payments"][0]["status"] == "paid"
    assert order["payments"][0]["pix"] is None


async def test_card_not_available(client, make_privileged_user):
    uh = await _setup(client, make_privileged_user)
    resp = await client.post("/api/v1/cart/checkout", json={"strategy": "single", "payment_method": "card"}, headers=uh)
    assert resp.status_code == 422
