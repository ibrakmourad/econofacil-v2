"""Serviço de Receitas.

Uma receita tem ingredientes com vínculo opcional a um produto do catálogo
(``product_id``). Isso permite converter a receita diretamente em compra —
só os ingredientes vinculados entram na conversão; os demais (ex.: "sal a
gosto") seguem só como texto informativo na receita.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recipe import Recipe, RecipeIngredient


async def list_recipes(
    db: AsyncSession, *, category_id: uuid.UUID | None = None, q: str | None = None
) -> list[Recipe]:
    stmt = select(Recipe)
    if category_id:
        stmt = stmt.where(Recipe.category_id == category_id)
    if q:
        stmt = stmt.where(Recipe.name.ilike(f"%{q}%"))
    stmt = stmt.order_by(Recipe.name)
    result = await db.execute(stmt)
    return list(result.scalars().unique().all())


async def get_recipe(db: AsyncSession, recipe_id: uuid.UUID) -> Recipe | None:
    return await db.get(Recipe, recipe_id)


async def get_recipe_by_slug(db: AsyncSession, slug: str) -> Recipe | None:
    result = await db.execute(select(Recipe).where(Recipe.slug == slug))
    return result.scalar_one_or_none()


async def create_recipe(
    db: AsyncSession,
    *,
    name: str,
    slug: str,
    description: str | None = None,
    image_url: str | None = None,
    servings: int = 2,
    prep_minutes: int | None = None,
    category_id: uuid.UUID | None = None,
    instructions: str | None = None,
) -> Recipe:
    recipe = Recipe(
        name=name, slug=slug.lower(), description=description, image_url=image_url,
        servings=servings, prep_minutes=prep_minutes, category_id=category_id,
        instructions=instructions,
    )
    db.add(recipe)
    await db.commit()
    await db.refresh(recipe)
    return recipe


async def add_ingredient(
    db: AsyncSession,
    recipe: Recipe,
    *,
    name: str,
    quantity: float = 1.0,
    unit: str | None = None,
    note: str | None = None,
    product_id: uuid.UUID | None = None,
) -> RecipeIngredient:
    position = len(recipe.ingredients)
    ing = RecipeIngredient(
        recipe_id=recipe.id, name=name, quantity=quantity, unit=unit,
        note=note, product_id=product_id, position=position,
    )
    db.add(ing)
    await db.commit()
    await db.refresh(ing)
    return ing


def linked_ingredients(recipe: Recipe) -> list[RecipeIngredient]:
    """Ingredientes com produto vinculado — os únicos convertíveis em compra."""
    return [i for i in recipe.ingredients if i.product_id is not None]


def scale_quantity(base_qty: float, base_servings: int, target_servings: int) -> int:
    """Escala a quantidade do ingrediente (unidades do produto do catálogo,
    não gramas/ml) para o número de porções desejado.

    Sempre arredonda para cima e nunca devolve menos de 1 — não faz sentido
    comprar "0.3 pacote" de um produto.
    """
    if base_servings <= 0 or target_servings <= 0:
        return max(1, round(base_qty))
    scaled = base_qty * (target_servings / base_servings)
    rounded_down = int(scaled)
    if scaled - rounded_down > 1e-9:
        rounded_down += 1
    return max(1, rounded_down)
