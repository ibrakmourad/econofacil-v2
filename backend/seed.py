"""Popula o banco com dados de demonstração para o EconoFácil.

Uso (com o ambiente do backend ativo e o DATABASE_URL configurado):

    python seed.py

Cria um admin, categorias, lojas e produtos com ofertas em preços variados —
o suficiente para o front-end mostrar catálogo, comparação de preços (RN-001) e
um split vantajoso (RN-018). É seguro rodar uma vez; se o admin já existir, sai.
"""
import asyncio

from app.core.database import AsyncSessionLocal, engine
from app.models import Base
from app.models.user import UserRole
from app.services import catalog_service, recipe_service, user_service

ADMIN = {"email": "admin@econofacil.com", "full_name": "Admin EconoFácil", "password": "admin12345"}

CATEGORIES = [
    ("Hortifruti", "hortifruti"),
    ("Mercearia", "mercearia"),
    ("Bebidas", "bebidas"),
    ("Limpeza", "limpeza"),
]

STORES = [
    ("Mercado Bom Preço", "bom-preco", "bompreco@pix.econofacil.demo"),
    ("SuperEconomia", "supereconomia", "supereconomia@pix.econofacil.demo"),
    ("Hiper Central", "hiper-central", None),  # sem chave própria -> cai na da plataforma
]

# produto: (nome, tamanho, unidade, categoria_slug, [preço em A, B, C] — None = não vende)
PRODUCTS = [
    ("Tomate Italiano", 1, "kg", "hortifruti", [5.49, 6.20, 5.90]),
    ("Banana Prata", 1, "kg", "hortifruti", [4.19, 3.99, 4.50]),
    ("Arroz Branco", 5, "kg", "mercearia", [24.90, 22.50, 26.00]),
    ("Feijão Carioca", 1, "kg", "mercearia", [8.90, 7.20, 8.10]),
    ("Macarrão Espaguete", 500, "g", "mercearia", [4.20, 4.80, 3.99]),
    ("Molho de Tomate", 340, "g", "mercearia", [2.99, 3.40, 2.79]),
    ("Leite Integral", 1, "l", "bebidas", [4.29, 4.59, 4.89]),
    ("Suco de Laranja", 1, "l", "bebidas", [8.90, 7.90, 9.20]),
    ("Detergente Neutro", 500, "ml", "limpeza", [2.49, 2.79, 2.29]),
]

# receita: (nome, slug, porções, minutos de preparo, descrição, [ingredientes])
# ingrediente: (nome exibido, quantidade, unidade, nome do produto no catálogo | None)
RECIPES = [
    (
        "Arroz com feijão", "arroz-com-feijao", 4, 40,
        "O clássico da mesa brasileira — simples, barato e rende bem.",
        [
            ("Arroz Branco", 1, "pacote", "Arroz Branco"),
            ("Feijão Carioca", 1, "pacote", "Feijão Carioca"),
            ("Sal", 1, None, None),
        ],
    ),
    (
        "Molho de tomate caseiro", "molho-de-tomate-caseiro", 4, 30,
        "Molho fresco de tomate para acompanhar o macarrão.",
        [
            ("Tomate Italiano", 4, "unidades", "Tomate Italiano"),
            ("Molho de Tomate", 1, "lata", "Molho de Tomate"),
            ("Macarrão Espaguete", 1, "pacote", "Macarrão Espaguete"),
            ("Manjericão", 1, None, None),
        ],
    ),
    (
        "Vitamina de banana", "vitamina-de-banana", 2, 5,
        "Vitamina rápida para o café da manhã.",
        [
            ("Banana Prata", 2, "unidades", "Banana Prata"),
            ("Leite Integral", 1, "litro", "Leite Integral"),
        ],
    ),
]


async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        if await user_service.get_by_email(db, ADMIN["email"]):
            print("Banco já parece populado (admin existe). Nada a fazer.")
            return

        await user_service.create_user(
            db, email=ADMIN["email"], full_name=ADMIN["full_name"],
            password=ADMIN["password"], role=UserRole.ADMIN,
        )

        cats = {}
        for name, slug in CATEGORIES:
            cats[slug] = await catalog_service.create_category(db, name=name, slug=slug)

        stores = [
            await catalog_service.create_store(db, name=n, slug=s, pix_key=pk)
            for n, s, pk in STORES
        ]

        products_by_name = {}
        for name, size, unit, cat_slug, prices in PRODUCTS:
            product = await catalog_service.create_product(
                db, name=name, package_size=size, package_unit=unit,
                category_id=cats[cat_slug].id,
            )
            products_by_name[name] = product
            for store, price in zip(stores, prices):
                if price is None:
                    continue
                await catalog_service.upsert_offer(
                    db, store_id=store.id, product_id=product.id,
                    price=price, original_price=None, in_stock=True, stock_quantity=100,
                )

        for name, slug, servings, prep, description, ingredients in RECIPES:
            recipe = await recipe_service.create_recipe(
                db, name=name, slug=slug, servings=servings,
                prep_minutes=prep, description=description,
            )
            for ing_name, qty, unit, product_name in ingredients:
                await recipe_service.add_ingredient(
                    db, recipe, name=ing_name, quantity=qty, unit=unit,
                    product_id=products_by_name[product_name].id if product_name else None,
                    note=None if product_name else "a gosto",
                )

    print("Seed concluído!")
    print(f"  Admin:  {ADMIN['email']} / {ADMIN['password']}")
    print(f"  {len(CATEGORIES)} categorias, {len(STORES)} lojas, {len(PRODUCTS)} produtos com ofertas.")
    print(f"  {len(RECIPES)} receitas de exemplo (com ingredientes vinculados ao catálogo).")
    print("  Cadastre um consumidor pelo app para comprar.")


if __name__ == "__main__":
    asyncio.run(main())
