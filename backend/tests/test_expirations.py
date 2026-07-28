"""Testes de expirações agendadas (RN-021).

Cobre tanto o uso oportunista (na leitura de um registro específico, que já
existia antes) quanto o novo disparo em lote — via o endpoint administrativo
(que por baixo chama a mesma função que o agendador de background usa) e via
o próprio módulo do agendador.
"""
from datetime import datetime, timedelta, timezone
import uuid

from sqlalchemy import select

from app.models.cart import Cart
from app.models.payment import Payment
from app.models.promotion import Promotion
from app.models.user import UserRole
from tests.conftest import TestSession

LOGIN = "/api/v1/auth/login"


async def _admin(client, make_privileged_user, email="expadm@ef.com"):
    await make_privileged_user(email, "AdminPass1", UserRole.ADMIN)
    tok = (await client.post(LOGIN, json={"email": email, "password": "AdminPass1"})).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


async def _consumer(client, email="expcli@ef.com"):
    await client.post("/api/v1/auth/register", json={"email": email, "full_name": "Cli", "password": "SenhaForte1"})
    tok = (await client.post(LOGIN, json={"email": email, "password": "SenhaForte1"})).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def _past() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()


# --------------------------------------------------------------------------- #
# Endpoint administrativo (disparo manual em lote)
# --------------------------------------------------------------------------- #
async def test_admin_expirations_requires_admin_role(client, make_privileged_user):
    ch = await _consumer(client)
    resp = await client.post("/api/v1/admin/expirations/run", headers=ch)
    assert resp.status_code == 403


async def test_admin_run_expires_carts_in_bulk(client, make_privileged_user, db):
    h = await _admin(client, make_privileged_user)
    prod = (await client.post("/api/v1/catalog/products", json={"name": "Arroz", "package_size": 5, "package_unit": "kg"}, headers=h)).json()["id"]
    store = (await client.post("/api/v1/catalog/stores", json={"name": "Loja Exp", "slug": "exp"}, headers=h)).json()["id"]
    await client.put(f"/api/v1/catalog/stores/{store}/offers/{prod}", json={"price": 10.0}, headers=h)

    stale = await _consumer(client, "stale@ef.com")
    fresh = await _consumer(client, "fresh@ef.com")
    await client.post("/api/v1/cart/items", json={"product_id": prod, "quantity": 1}, headers=stale)
    await client.post("/api/v1/cart/items", json={"product_id": prod, "quantity": 1}, headers=fresh)

    # expira manualmente só o carrinho do "stale"
    carts = (await db.execute(select(Cart))).scalars().all()
    # como não temos o e-mail no Cart, expira o carrinho mais antigo (o do "stale",
    # que foi o primeiro a ser criado, já que "fresh" veio na sequência)
    carts_sorted = sorted(carts, key=lambda c: c.created_at)
    carts_sorted[0].expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await db.commit()

    result = (await client.post("/api/v1/admin/expirations/run", headers=h)).json()
    assert result["carts_expired"] == 1

    stale_cart = (await client.get("/api/v1/cart", headers=stale)).json()
    assert stale_cart["item_count"] == 0   # foi expirado e recriado vazio

    fresh_cart = (await client.get("/api/v1/cart", headers=fresh)).json()
    assert fresh_cart["item_count"] == 1   # não foi afetado


async def test_admin_run_expires_promotions_in_bulk(client, make_privileged_user, db):
    ha = await _admin(client, make_privileged_user, "padm1@ef.com")
    prod_a = (await client.post("/api/v1/catalog/products", json={"name": "Feijão", "package_size": 1, "package_unit": "kg"}, headers=ha)).json()["id"]
    store_a = (await client.post("/api/v1/catalog/stores", json={"name": "Loja PA", "slug": "pa"}, headers=ha)).json()["id"]
    await client.put(f"/api/v1/catalog/stores/{store_a}/offers/{prod_a}", json={"price": 10.0}, headers=ha)

    prod_b = (await client.post("/api/v1/catalog/products", json={"name": "Macarrão", "package_size": 500, "package_unit": "g"}, headers=ha)).json()["id"]
    store_b = (await client.post("/api/v1/catalog/stores", json={"name": "Loja PB", "slug": "pb"}, headers=ha)).json()["id"]
    await client.put(f"/api/v1/catalog/stores/{store_b}/offers/{prod_b}", json={"price": 6.0}, headers=ha)

    future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    await client.post(f"/api/v1/merchant/stores/{store_a}/promotions", json={"product_id": prod_a, "promo_price": 7.0, "ends_at": future}, headers=ha)
    await client.post(f"/api/v1/merchant/stores/{store_b}/promotions", json={"product_id": prod_b, "promo_price": 4.0, "ends_at": future}, headers=ha)

    # vence só a promoção da loja A
    promos = (await db.execute(select(Promotion))).scalars().all()
    promo_a = next(p for p in promos if str(p.store_id) == store_a)
    promo_a.ends_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await db.commit()

    result = (await client.post("/api/v1/admin/expirations/run", headers=ha)).json()
    assert result["promotions_expired"] == 1

    pdp_a = (await client.get(f"/api/v1/catalog/products/{prod_a}")).json()
    assert pdp_a["offers"][0]["price"] == 10.0   # restaurado

    pdp_b = (await client.get(f"/api/v1/catalog/products/{prod_b}")).json()
    assert pdp_b["offers"][0]["price"] == 4.0    # ainda em promoção


async def test_admin_run_expires_pix_charges_and_cancels_order(client, make_privileged_user, db):
    h = await _admin(client, make_privileged_user, "pixadm@ef.com")
    prod = (await client.post("/api/v1/catalog/products", json={"name": "Arroz Pix", "package_size": 5, "package_unit": "kg"}, headers=h)).json()["id"]
    store = (await client.post("/api/v1/catalog/stores", json={"name": "Loja Pix", "slug": "pix"}, headers=h)).json()["id"]
    await client.put(f"/api/v1/catalog/stores/{store}/offers/{prod}", json={"price": 20.0}, headers=h)

    ch = await _consumer(client, "pixexp@ef.com")
    await client.post("/api/v1/cart/items", json={"product_id": prod, "quantity": 1}, headers=ch)
    order = (await client.post("/api/v1/cart/checkout", json={"strategy": "single", "payment_method": "pix"}, headers=ch)).json()
    assert order["status"] == "awaiting_payment"
    payment_id = order["payments"][0]["id"]

    # vence a cobrança Pix
    payment = await db.get(Payment, uuid.UUID(payment_id))
    payment.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await db.commit()

    result = (await client.post("/api/v1/admin/expirations/run", headers=h)).json()
    assert result["pix_charges_expired"] == 1

    detail = (await client.get(f"/api/v1/orders/{order['id']}", headers=ch)).json()
    assert detail["status"] == "cancelled"
    assert all(f["status"] == "cancelled" for f in detail["fulfillments"])
    assert detail["payments"][0]["status"] == "expired"


async def test_pix_charge_expires_opportunistically_on_read(client, make_privileged_user, db):
    """Mesmo sem rodar o job em lote, ler o pagamento/pedido vencido já reflete a expiração."""
    h = await _admin(client, make_privileged_user, "pixopp@ef.com")
    prod = (await client.post("/api/v1/catalog/products", json={"name": "Feijão Pix", "package_size": 1, "package_unit": "kg"}, headers=h)).json()["id"]
    store = (await client.post("/api/v1/catalog/stores", json={"name": "Loja PixOpp", "slug": "pixopp"}, headers=h)).json()["id"]
    await client.put(f"/api/v1/catalog/stores/{store}/offers/{prod}", json={"price": 8.0}, headers=h)

    ch = await _consumer(client, "pixopp_cli@ef.com")
    await client.post("/api/v1/cart/items", json={"product_id": prod, "quantity": 1}, headers=ch)
    order = (await client.post("/api/v1/cart/checkout", json={"strategy": "single", "payment_method": "pix"}, headers=ch)).json()
    payment_id = order["payments"][0]["id"]

    payment = await db.get(Payment, uuid.UUID(payment_id))
    payment.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await db.commit()

    # sem chamar /admin/expirations/run — só lendo o pagamento
    pay = (await client.get(f"/api/v1/payments/{payment_id}", headers=ch)).json()
    assert pay["status"] == "expired"

    detail = (await client.get(f"/api/v1/orders/{order['id']}", headers=ch)).json()
    assert detail["status"] == "cancelled"


# --------------------------------------------------------------------------- #
# O agendador em si (laço de background)
# --------------------------------------------------------------------------- #
async def test_scheduler_run_once_reports_summary(monkeypatch, client, make_privileged_user, db):
    import app.core.scheduler as scheduler

    # a engine "de produção" do app.core.database não é a do banco de teste;
    # trocamos por uma sessão apontando para o mesmo engine usado nos testes.
    monkeypatch.setattr(scheduler, "AsyncSessionLocal", TestSession)

    h = await _admin(client, make_privileged_user, "sched@ef.com")
    prod = (await client.post("/api/v1/catalog/products", json={"name": "Sabão", "package_size": 500, "package_unit": "g"}, headers=h)).json()["id"]
    store = (await client.post("/api/v1/catalog/stores", json={"name": "Loja Sched", "slug": "sched"}, headers=h)).json()["id"]
    await client.put(f"/api/v1/catalog/stores/{store}/offers/{prod}", json={"price": 3.0}, headers=h)

    ch = await _consumer(client, "sched_cli@ef.com")
    await client.post("/api/v1/cart/items", json={"product_id": prod, "quantity": 1}, headers=ch)

    carts = (await db.execute(select(Cart))).scalars().all()
    carts[0].expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await db.commit()

    summary = await scheduler.run_once()
    assert summary["carts_expired"] == 1


def test_scheduler_start_stop_lifecycle():
    import asyncio

    async def _run():
        import app.core.scheduler as scheduler
        from app.core.config import settings

        original_interval = settings.SCHEDULER_INTERVAL_SECONDS
        settings.SCHEDULER_INTERVAL_SECONDS = 3600  # não deixa o laço rodar de novo durante o teste
        try:
            assert scheduler.is_running() is False
            scheduler.start()
            assert scheduler.is_running() is True
            scheduler.start()  # chamar de novo não deve duplicar a task
            assert scheduler.is_running() is True
            await scheduler.stop()
            assert scheduler.is_running() is False
            await scheduler.stop()  # parar de novo não deve quebrar
        finally:
            settings.SCHEDULER_INTERVAL_SECONDS = original_interval

    asyncio.run(_run())
