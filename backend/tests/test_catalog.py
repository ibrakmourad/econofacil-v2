"""Testes do módulo de catálogo: normalização e comparação de preços."""
import pytest

from app.core.units import UnknownUnitError, normalize, unit_price
from app.models.user import UserRole

LOGIN = "/api/v1/auth/login"


# --------------------------------------------------------------------------- #
# Unitários (RN-001)
# --------------------------------------------------------------------------- #
def test_normalize_volume():
    assert normalize(2, "L") == ("volume", "l", 2.0)


def test_normalize_weight_grams_to_kg():
    assert normalize(500, "g") == ("weight", "kg", 0.5)


def test_normalize_rejects_unknown_unit():
    with pytest.raises(UnknownUnitError):
        normalize(1, "litro")


def test_unit_price_normalizes_per_base_unit():
    # 6 unidades por R$ 25,74 -> R$ 4,29/un
    assert unit_price(25.74, 6) == 4.29
    # 2L por R$ 8,00 -> R$ 4,00/l, mais caro por litro que 1L por R$ 3,50
    assert unit_price(8.0, 2.0) > unit_price(3.5, 1.0)


# --------------------------------------------------------------------------- #
# Integração
# --------------------------------------------------------------------------- #
async def _admin_headers(client, make_privileged_user):
    await make_privileged_user("admin@econofacil.com", "AdminPass123", UserRole.ADMIN)
    resp = await client.post(
        LOGIN, json={"email": "admin@econofacil.com", "password": "AdminPass123"}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_consumer_cannot_create_product(client):
    await client.post(
        "/api/v1/auth/register",
        json={"email": "c@x.com", "full_name": "Cli", "password": "SenhaForte1"},
    )
    login = await client.post(LOGIN, json={"email": "c@x.com", "password": "SenhaForte1"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    resp = await client.post(
        "/api/v1/catalog/products",
        json={"name": "X", "package_size": 1, "package_unit": "un"},
        headers=headers,
    )
    assert resp.status_code == 403


async def test_public_register_cannot_become_admin(client):
    # mesmo enviando 'role', o cadastro ignora e cria consumidor
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "hacker@x.com",
            "full_name": "Hacker",
            "password": "SenhaForte1",
            "role": "admin",
        },
    )
    login = await client.post(LOGIN, json={"email": "hacker@x.com", "password": "SenhaForte1"})
    me = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert me.json()["role"] == "consumer"


async def test_price_comparison_flow(client, make_privileged_user):
    headers = await _admin_headers(client, make_privileged_user)

    # categoria + produto (Leite 1L)
    cat = await client.post(
        "/api/v1/catalog/categories",
        json={"name": "Mercearia", "slug": "mercearia"},
        headers=headers,
    )
    cat_id = cat.json()["id"]

    prod = await client.post(
        "/api/v1/catalog/products",
        json={
            "name": "Leite Integral 1L",
            "package_size": 1,
            "package_unit": "L",
            "category_id": cat_id,
        },
        headers=headers,
    )
    assert prod.status_code == 201
    pid = prod.json()["id"]
    assert prod.json()["base_unit"] == "l"

    # duas lojas
    s1 = (await client.post(
        "/api/v1/catalog/stores",
        json={"name": "Mercado Bom Preço", "slug": "bom-preco"}, headers=headers,
    )).json()["id"]
    s2 = (await client.post(
        "/api/v1/catalog/stores",
        json={"name": "SuperEconomia", "slug": "supereconomia"}, headers=headers,
    )).json()["id"]

    # ofertas: loja 1 mais barata
    await client.put(
        f"/api/v1/catalog/stores/{s1}/offers/{pid}",
        json={"price": 4.29, "original_price": 5.10, "in_stock": True}, headers=headers,
    )
    await client.put(
        f"/api/v1/catalog/stores/{s2}/offers/{pid}",
        json={"price": 4.89, "in_stock": True}, headers=headers,
    )

    # comparação (PDP) — a melhor oferta deve ser a loja 1
    cmp = await client.get(f"/api/v1/catalog/products/{pid}")
    assert cmp.status_code == 200
    data = cmp.json()
    assert data["best_unit_price"] == 4.29
    assert data["unit_label"] == "R$/l"
    assert len(data["offers"]) == 2
    assert data["offers"][0]["store_name"] == "Mercado Bom Preço"
    assert data["offers"][0]["is_best"] is True

    # listagem por menor preço
    lst = await client.get("/api/v1/catalog/products?sort=price")
    body = lst.json()
    assert body["total"] == 1
    assert body["items"][0]["best_unit_price"] == 4.29
    assert body["items"][0]["store_count"] == 2

    # busca por nome
    found = await client.get("/api/v1/catalog/products?q=leite")
    assert found.json()["total"] == 1
    empty = await client.get("/api/v1/catalog/products?q=café")
    assert empty.json()["total"] == 0
