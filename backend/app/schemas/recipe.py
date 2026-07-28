"""Schemas de Receitas."""
from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field


class RecipeIngredientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    quantity: float = Field(default=1.0, gt=0)
    unit: str | None = Field(default=None, max_length=40)
    note: str | None = Field(default=None, max_length=200)
    product_id: uuid.UUID | None = None


class RecipeIngredientView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    product_id: uuid.UUID | None = None
    name: str
    quantity: float
    unit: str | None = None
    note: str | None = None
    linked: bool = False

    @classmethod
    def from_model(cls, ing) -> "RecipeIngredientView":
        return cls(
            id=ing.id, product_id=ing.product_id, name=ing.name,
            quantity=ing.quantity, unit=ing.unit, note=ing.note,
            linked=ing.product_id is not None,
        )


class RecipeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    slug: str = Field(min_length=1, max_length=160)
    description: str | None = None
    image_url: str | None = None
    servings: int = Field(default=2, ge=1)
    prep_minutes: int | None = Field(default=None, ge=0)
    category_id: uuid.UUID | None = None
    instructions: str | None = None


class RecipeSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    slug: str
    description: str | None = None
    image_url: str | None = None
    servings: int
    prep_minutes: int | None = None
    ingredient_count: int = 0


class RecipeDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    slug: str
    description: str | None = None
    image_url: str | None = None
    servings: int
    prep_minutes: int | None = None
    instructions: str | None = None
    ingredients: list[RecipeIngredientView] = []
    linked_ingredient_count: int = 0
