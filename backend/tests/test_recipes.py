"""Testes do módulo de Receitas."""
from app.models.user import UserRole

LOGIN = "/api/v1/auth/login"


async def _admin(client, make_privileged_user):
    await make_privileged_user("radm@ef.com", "AdminPass1", UserRole.ADMIN)
    tok = (await client.post(LOGIN, json={"email": "radm@ef.com", "password": "AdminPass1"})).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


async def _consumer(client, email="rcli@ef.com"):
    await client.post("/api/v1/auth/register", json={"email": email, "full_name": "Cli", "password": "SenhaForte1"})
    tok = (await client.post(LOGIN, json={"email": email, "password": "SenhaForte1"})).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


async def _catalog_with_store(client, h):
    tomate = (await client.post("/api/v1/catalog/products", json={"name": "Tomate", "package_size": 1, "package_unit": "kg"}, headers=h)).json()["id"]
    macarrao = (await client.post("/api/v1/catalog/products", json={"name": "Macarrão", "package_size": 500, "package_unit": "g"}, headers=h)).json()["id"]
    store = (await client.post("/api/v1/catalog/stores", json={"name": "Loja Receita", "slug": "receita"}, headers=h)).json()["id"]
    await client.put(f"/api/v1/catalog/stores/{store}/offers/{tomate}", json={"price": 5.0}, headers=h)
    await client.put(f"/api/v1/catalog/stores/{store}/offers/{macarrao}", json={"price": 4.0}, headers=h)
    return tomate, macarrao


async def test_create_recipe_with_ingredients(client, make_privileged_user):
    h = await _admin(client, make_privileged_user)
    tomate, macarrao = await _catalog_with_store(client, h)

    recipe = (await client.post(
        "/api/v1/recipes",
        json={"name": "Macarrão com molho", "slug": "macarrao-molho", "servings": 2, "prep_minutes": 20},
        headers=h,
    )).json()
    assert recipe["ingredients"] == []

    await client.post(
        f"/api/v1/recipes/{recipe['id']}/ingredients",
        json={"name": "Tomate", "quantity": 2, "product_id": tomate},
        headers=h,
    )
    await client.post(
        f"/api/v1/recipes/{recipe['id']}/ingredients",
        json={"name": "Macarrão", "quantity": 1, "product_id": macarrao},
        headers=h,
    )
    await client.post(
        f"/api/v1/recipes/{recipe['id']}/ingredients",
        json={"name": "Sal", "quantity": 1, "note": "a gosto"},  # sem product_id
        headers=h,
    )

    detail = (await client.get(f"/api/v1/recipes/{recipe['id']}")).json()
    assert len(detail["ingredients"]) == 3
    assert detail["linked_ingredient_count"] == 2
    salt = next(i for i in detail["ingredients"] if i["name"] == "Sal")
    assert salt["linked"] is False

    listed = (await client.get("/api/v1/recipes")).json()
    assert any(r["slug"] == "macarrao-molho" for r in listed)


async def test_duplicate_slug_rejected(client, make_privileged_user):
    h = await _admin(client, make_privileged_user)
    await client.post("/api/v1/recipes", json={"name": "A", "slug": "dup"}, headers=h)
    dup = await client.post("/api/v1/recipes", json={"name": "B", "slug": "dup"}, headers=h)
    assert dup.status_code == 409


async def test_consumer_cannot_create_recipe(client):
    ch = await _consumer(client, "noadmin@ef.com")
    resp = await client.post("/api/v1/recipes", json={"name": "X", "slug": "x"}, headers=ch)
    assert resp.status_code == 403


async def test_add_recipe_to_cart_scales_by_servings(client, make_privileged_user):
    h = await _admin(client, make_privileged_user)
    tomate, macarrao = await _catalog_with_store(client, h)
    recipe = (await client.post(
        "/api/v1/recipes",
        json={"name": "Molho de tomate", "slug": "molho-tomate", "servings": 2},
        headers=h,
    )).json()
    await client.post(f"/api/v1/recipes/{recipe['id']}/ingredients", json={"name": "Tomate", "quantity": 2, "product_id": tomate}, headers=h)
    await client.post(f"/api/v1/recipes/{recipe['id']}/ingredients", json={"name": "Macarrão", "quantity": 1, "product_id": macarrao}, headers=h)

    ch = await _consumer(client, "scale@ef.com")
    # o dobro de porções -> quantidades dobradas
    cart = (await client.post(f"/api/v1/recipes/{recipe['id']}/add-to-cart?servings=4", headers=ch)).json()
    by_name = {i["name"]: i["quantity"] for i in cart["items"]}
    assert by_name["Tomate"] == 4
    assert by_name["Macarrão"] == 2


async def test_recipe_without_linked_ingredients_cannot_be_added_to_cart(client, make_privileged_user):
    h = await _admin(client, make_privileged_user)
    recipe = (await client.post("/api/v1/recipes", json={"name": "Só sal", "slug": "so-sal"}, headers=h)).json()
    await client.post(f"/api/v1/recipes/{recipe['id']}/ingredients", json={"name": "Sal", "note": "a gosto"}, headers=h)

    ch = await _consumer(client, "nolink@ef.com")
    resp = await client.post(f"/api/v1/recipes/{recipe['id']}/add-to-cart", headers=ch)
    assert resp.status_code == 422
