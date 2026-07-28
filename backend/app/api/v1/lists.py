"""Endpoints de Listas de compras (/lists).

Toda lista é privada ao dono — diferente do catálogo/receitas, não há leitura
pública aqui.
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser
from app.schemas.cart import OptimizeResult
from app.schemas.shopping_list import (
    AddListItemRequest,
    AddToCartResult,
    ListCreate,
    ListRename,
    ListSummary,
    ListView,
    SetListItemQuantityRequest,
)
from app.services import list_service

router = APIRouter(prefix="/lists", tags=["lists"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def _owned(db: AsyncSession, user, list_id: uuid.UUID):
    lst = await list_service.get_owned_list(db, user, list_id)
    if lst is None:
        raise HTTPException(status_code=404, detail="Lista não encontrada")
    return lst


def _summary(lst) -> ListSummary:
    return ListSummary(
        id=lst.id, name=lst.name, item_count=sum(i.quantity for i in lst.items),
        created_at=lst.created_at, updated_at=lst.updated_at,
    )


# --------------------------------------------------------------------------- #
# Listas
# --------------------------------------------------------------------------- #
@router.get("", response_model=list[ListSummary])
async def my_lists(db: DbSession, user: CurrentUser):
    lists = await list_service.list_my_lists(db, user)
    return [_summary(l) for l in lists]


@router.post("", response_model=ListSummary, status_code=status.HTTP_201_CREATED)
async def create_list(payload: ListCreate, db: DbSession, user: CurrentUser):
    lst = await list_service.create_list(db, user, payload.name)
    return _summary(lst)


@router.get("/{list_id}", response_model=ListView)
async def get_list(list_id: uuid.UUID, db: DbSession, user: CurrentUser):
    lst = await _owned(db, user, list_id)
    return ListView(**await list_service.build_view(db, lst))


@router.patch("/{list_id}", response_model=ListSummary)
async def rename_list(list_id: uuid.UUID, payload: ListRename, db: DbSession, user: CurrentUser):
    lst = await _owned(db, user, list_id)
    lst = await list_service.rename_list(db, lst, payload.name)
    return _summary(lst)


@router.delete("/{list_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_list(list_id: uuid.UUID, db: DbSession, user: CurrentUser):
    lst = await _owned(db, user, list_id)
    await list_service.delete_list(db, lst)


# --------------------------------------------------------------------------- #
# Itens
# --------------------------------------------------------------------------- #
@router.post("/{list_id}/items", response_model=ListView)
async def add_item(list_id: uuid.UUID, payload: AddListItemRequest, db: DbSession, user: CurrentUser):
    lst = await _owned(db, user, list_id)
    try:
        lst = await list_service.add_item(db, lst, payload.product_id, payload.quantity)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return ListView(**await list_service.build_view(db, lst))


@router.patch("/{list_id}/items/{product_id}", response_model=ListView)
async def set_quantity(
    list_id: uuid.UUID, product_id: uuid.UUID, payload: SetListItemQuantityRequest,
    db: DbSession, user: CurrentUser,
):
    lst = await _owned(db, user, list_id)
    try:
        lst = await list_service.set_item_quantity(db, lst, product_id, payload.quantity)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return ListView(**await list_service.build_view(db, lst))


@router.delete("/{list_id}/items/{product_id}", response_model=ListView)
async def remove_item(list_id: uuid.UUID, product_id: uuid.UUID, db: DbSession, user: CurrentUser):
    lst = await _owned(db, user, list_id)
    lst = await list_service.remove_item(db, lst, product_id)
    return ListView(**await list_service.build_view(db, lst))


# --------------------------------------------------------------------------- #
# Comparação de preços (RN-018) e cópia para o carrinho
# --------------------------------------------------------------------------- #
@router.get("/{list_id}/compare", response_model=OptimizeResult)
async def compare_list(list_id: uuid.UUID, db: DbSession, user: CurrentUser):
    lst = await _owned(db, user, list_id)
    plan = await list_service.compare(db, lst)
    return OptimizeResult(**plan)


@router.post("/{list_id}/add-to-cart", response_model=AddToCartResult)
async def add_list_to_cart(list_id: uuid.UUID, db: DbSession, user: CurrentUser):
    lst = await _owned(db, user, list_id)
    result = await list_service.add_to_cart(db, user, lst)
    return AddToCartResult(**result)
