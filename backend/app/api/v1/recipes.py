"""Endpoints de Receitas (/recipes).

Leitura é pública (como o catálogo). Criação de receita e adição de
ingredientes ficam restritas a comerciante/admin — são conteúdo curado,
como já era no front (ver Documento Mestre, seção 4.3, mesmo padrão do
catálogo). Qualquer consumidor logado pode converter uma receita em itens
no seu carrinho.
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, require_role
from app.models.user import UserRole
from app.schemas.cart import CartView
from app.schemas.recipe import (
    RecipeCreate,
    RecipeDetail,
    RecipeIngredientCreate,
    RecipeIngredientView,
    RecipeSummary,
)
from app.services import cart_service, recipe_service

router = APIRouter(prefix="/recipes", tags=["recipes"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
MerchantOrAdmin = Annotated[object, Depends(require_role(UserRole.MERCHANT, UserRole.ADMIN))]


def _detail(recipe) -> RecipeDetail:
    ingredients = [RecipeIngredientView.from_model(i) for i in recipe.ingredients]
    return RecipeDetail(
        id=recipe.id, name=recipe.name, slug=recipe.slug, description=recipe.description,
        image_url=recipe.image_url, servings=recipe.servings, prep_minutes=recipe.prep_minutes,
        instructions=recipe.instructions, ingredients=ingredients,
        linked_ingredient_count=sum(1 for i in ingredients if i.linked),
    )


# --------------------------------------------------------------------------- #
# Leitura — pública
# --------------------------------------------------------------------------- #
@router.get("", response_model=list[RecipeSummary])
async def list_recipes(
    db: DbSession,
    category_id: uuid.UUID | None = None,
    q: str | None = Query(default=None, description="Busca por nome"),
):
    recipes = await recipe_service.list_recipes(db, category_id=category_id, q=q)
    return [
        RecipeSummary(
            id=r.id, name=r.name, slug=r.slug, description=r.description,
            image_url=r.image_url, servings=r.servings, prep_minutes=r.prep_minutes,
            ingredient_count=len(r.ingredients),
        )
        for r in recipes
    ]


@router.get("/{recipe_id}", response_model=RecipeDetail)
async def get_recipe(recipe_id: uuid.UUID, db: DbSession):
    recipe = await recipe_service.get_recipe(db, recipe_id)
    if recipe is None:
        raise HTTPException(status_code=404, detail="Receita não encontrada")
    return _detail(recipe)


# --------------------------------------------------------------------------- #
# Escrita — comerciante / admin (conteúdo curado)
# --------------------------------------------------------------------------- #
@router.post("", response_model=RecipeDetail, status_code=status.HTTP_201_CREATED)
async def create_recipe(payload: RecipeCreate, db: DbSession, _: MerchantOrAdmin):
    existing = await recipe_service.get_recipe_by_slug(db, payload.slug)
    if existing is not None:
        raise HTTPException(status_code=409, detail="Já existe uma receita com este slug")
    recipe = await recipe_service.create_recipe(db, **payload.model_dump())
    return _detail(recipe)


@router.post(
    "/{recipe_id}/ingredients",
    response_model=RecipeIngredientView,
    status_code=status.HTTP_201_CREATED,
)
async def add_ingredient(
    recipe_id: uuid.UUID, payload: RecipeIngredientCreate, db: DbSession, _: MerchantOrAdmin
):
    recipe = await recipe_service.get_recipe(db, recipe_id)
    if recipe is None:
        raise HTTPException(status_code=404, detail="Receita não encontrada")
    ing = await recipe_service.add_ingredient(
        db, recipe,
        name=payload.name, quantity=payload.quantity, unit=payload.unit,
        note=payload.note, product_id=payload.product_id,
    )
    return RecipeIngredientView.from_model(ing)


# --------------------------------------------------------------------------- #
# Receita -> carrinho
# --------------------------------------------------------------------------- #
@router.post("/{recipe_id}/add-to-cart", response_model=CartView)
async def add_recipe_to_cart(
    recipe_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    servings: int | None = Query(
        default=None, ge=1, description="Porções desejadas (padrão: as da receita)"
    ),
):
    """Adiciona ao carrinho os ingredientes vinculados ao catálogo, escalando
    as quantidades para o número de porções desejado (RN-020)."""
    recipe = await recipe_service.get_recipe(db, recipe_id)
    if recipe is None:
        raise HTTPException(status_code=404, detail="Receita não encontrada")

    linked = recipe_service.linked_ingredients(recipe)
    if not linked:
        raise HTTPException(
            status_code=422,
            detail="Esta receita não tem ingredientes vinculados ao catálogo",
        )

    target = servings or recipe.servings
    cart = await cart_service.get_active_cart(db, user)
    for ing in linked:
        qty = recipe_service.scale_quantity(ing.quantity, recipe.servings, target)
        cart = await cart_service.add_item(db, cart, ing.product_id, qty)

    return CartView(**await cart_service.build_view(db, cart))
