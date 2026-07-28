"""Testes do módulo de Listas de compras."""
from app.models.user import UserRole

LOGIN = "/api/v1/auth/login"


async def _admin(client, make_privileged_user):
    await make_privileged_user("ladm@ef.com", "AdminPass1", UserRole.ADMIN)
    tok = (await client.post(LOGIN, json={"email": "ladm@ef.com", "password": "AdminPass1"})).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


async def _consumer(client, email="lcli@ef.com"):
    await client.post("/api/v1/auth/register", json={"email": email, "full_name": "Cli", "password": "SenhaForte1"})
    tok = (await client.post(LOGIN, json={"email": email, "password": "SenhaForte1"})).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


async def _split_catalog(client, h):
    """Arroz mais barato na Loja A; Feijão mais barato na Loja B -> split compensa."""
    arroz = (await client.post("/api/v1/catalog/products", json={"name": "Arroz 5kg", "package_size": 5, "package_unit": "kg"}, headers=h)).json()["id"]
    feijao = (await client.post("/api/v1/catalog/products", json={"name": "Feijão 1kg", "package_size": 1, "package_unit": "kg"}, headers=h)).json()["id"]
    sa = (await client.post("/api/v1/catalog/stores", json={"name": "Loja LA", "slug": "la"}, headers=h)).json()["id"]
    sb = (await client.post("/api/v1/catalog/stores", json={"name": "Loja LB", "slug": "lb"}, headers=h)).json()["id"]
    await client.put(f"/api/v1/catalog/stores/{sa}/offers/{arroz}", json={"price": 20.0}, headers=h)
    await client.put(f"/api/v1/catalog/stores/{sb}/offers/{arroz}", json={"price": 25.0}, headers=h)
    await client.put(f"/api/v1/catalog/stores/{sa}/offers/{feijao}", json={"price": 12.0}, headers=h)
    await client.put(f"/api/v1/catalog/stores/{sb}/offers/{feijao}", json={"price": 8.0}, headers=h)
    return arroz, feijao


async def test_create_list_and_manage_items(client, make_privileged_user):
    h = await _admin(client, make_privileged_user)
    arroz, feijao = await _split_catalog(client, h)
    ch = await _consumer(client, "manage@ef.com")

    created = await client.post("/api/v1/lists", json={"name": "Feira da semana"}, headers=ch)
    assert created.status_code == 201
    list_id = created.json()["id"]
    assert created.json()["item_count"] == 0

    view = (await client.post(f"/api/v1/lists/{list_id}/items", json={"product_id": arroz, "quantity": 2}, headers=ch)).json()
    assert view["item_count"] == 2
    view = (await client.post(f"/api/v1/lists/{list_id}/items", json={"product_id": feijao, "quantity": 1}, headers=ch)).json()
    assert view["item_count"] == 3
    assert view["subtotal_estimate"] == 2 * 20.0 + 1 * 8.0   # melhores preços (Loja LA e LB)

    # ajustar quantidade
    view = (await client.patch(f"/api/v1/lists/{list_id}/items/{arroz}", json={"quantity": 1}, headers=ch)).json()
    assert view["item_count"] == 2

    # remover item
    view = (await client.delete(f"/api/v1/lists/{list_id}/items/{feijao}", headers=ch)).json()
    assert view["item_count"] == 1

    # renomear
    renamed = (await client.patch(f"/api/v1/lists/{list_id}", json={"name": "Feira renomeada"}, headers=ch)).json()
    assert renamed["name"] == "Feira renomeada"

    listed = (await client.get("/api/v1/lists", headers=ch)).json()
    assert len(listed) == 1 and listed[0]["name"] == "Feira renomeada"

    deleted = await client.delete(f"/api/v1/lists/{list_id}", headers=ch)
    assert deleted.status_code == 204
    assert (await client.get("/api/v1/lists", headers=ch)).json() == []


async def test_list_is_private_to_owner(client, make_privileged_user):
    h = await _admin(client, make_privileged_user)
    arroz, _ = await _split_catalog(client, h)
    owner = await _consumer(client, "owner@ef.com")
    intruder = await _consumer(client, "intruder@ef.com")

    lst = (await client.post("/api/v1/lists", json={"name": "Minha lista"}, headers=owner)).json()
    await client.post(f"/api/v1/lists/{lst['id']}/items", json={"product_id": arroz, "quantity": 1}, headers=owner)

    resp = await client.get(f"/api/v1/lists/{lst['id']}", headers=intruder)
    assert resp.status_code == 404


async def test_compare_list_recommends_split(client, make_privileged_user):
    h = await _admin(client, make_privileged_user)
    arroz, feijao = await _split_catalog(client, h)
    ch = await _consumer(client, "compare@ef.com")

    lst = (await client.post("/api/v1/lists", json={"name": "Compra do mês"}, headers=ch)).json()
    await client.post(f"/api/v1/lists/{lst['id']}/items", json={"product_id": arroz, "quantity": 1}, headers=ch)
    await client.post(f"/api/v1/lists/{lst['id']}/items", json={"product_id": feijao, "quantity": 1}, headers=ch)

    cmp = (await client.get(f"/api/v1/lists/{lst['id']}/compare", headers=ch)).json()
    assert cmp["recommended"] == "split"
    assert cmp["single_store"]["total"] == 32.0
    assert cmp["split"]["total"] == 28.0
    assert cmp["savings"] == 4.0


async def test_add_list_to_cart_merges_with_existing_items(client, make_privileged_user):
    h = await _admin(client, make_privileged_user)
    arroz, feijao = await _split_catalog(client, h)
    ch = await _consumer(client, "tocart@ef.com")

    # já tem 1 arroz no carrinho antes de copiar a lista
    await client.post("/api/v1/cart/items", json={"product_id": arroz, "quantity": 1}, headers=ch)

    lst = (await client.post("/api/v1/lists", json={"name": "Lista p/ carrinho"}, headers=ch)).json()
    await client.post(f"/api/v1/lists/{lst['id']}/items", json={"product_id": arroz, "quantity": 2}, headers=ch)
    await client.post(f"/api/v1/lists/{lst['id']}/items", json={"product_id": feijao, "quantity": 3}, headers=ch)

    result = (await client.post(f"/api/v1/lists/{lst['id']}/add-to-cart", headers=ch)).json()
    assert result["added"] == 2
    assert result["skipped_unavailable"] == 0

    cart = (await client.get("/api/v1/cart", headers=ch)).json()
    by_pid = {i["product_id"]: i["quantity"] for i in cart["items"]}
    assert by_pid[arroz] == 3     # 1 (já no carrinho) + 2 (da lista)
    assert by_pid[feijao] == 3
