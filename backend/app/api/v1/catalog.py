"""Endpoints do catálogo (/catalog)."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, require_role
from app.core.units import UnknownUnitError
from app.models.user import UserRole
from app.schemas.catalog import (
    CategoryCreate,
    CategoryPublic,
    OfferUpsert,
    ProductBase,
    ProductComparison,
    ProductCreate,
    ProductList,
    ProductWithBestPrice,
    StoreCreate,
    StoreOffer,
    StorePublic,
)
from app.services import catalog_service
from app.services.audit_service import log_action

router = APIRouter(prefix="/catalog", tags=["catalog"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
MerchantOrAdmin = Annotated[
    object, Depends(require_role(UserRole.MERCHANT, UserRole.ADMIN))
]


# --------------------------------------------------------------------------- #
# Leitura — consumidor
# --------------------------------------------------------------------------- #
@router.get("/categories", response_model=list[CategoryPublic])
async def list_categories(db: DbSession):
    return await catalog_service.list_categories(db)


@router.get("/products", response_model=ProductList)
async def list_products(
    db: DbSession,
    q: str | None = Query(default=None, description="Busca por nome"),
    category_id: uuid.UUID | None = None,
    sort: str = Query(default="price", pattern="^(price|name)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    items, total = await catalog_service.list_products(
        db, q=q, category_id=category_id, sort=sort, page=page, page_size=page_size
    )
    return ProductList(
        items=[
            ProductWithBestPrice(
                **ProductBase.model_validate(it["product"]).model_dump(),
                best_unit_price=it["best_unit_price"],
                unit_label=it["unit_label"],
                store_count=it["store_count"],
            )
            for it in items
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/products/{product_id}", response_model=ProductComparison)
async def compare_product(product_id: uuid.UUID, db: DbSession):
    product = await catalog_service.get_product(db, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    offers, best = await catalog_service.compare_product(db, product)
    base = ProductBase.model_validate(product).model_dump()
    base.update(
        {
            "offers": [StoreOffer(**o) for o in offers],
            "best_unit_price": best,
            "unit_label": f"R$/{product.base_unit}",
        }
    )
    return ProductComparison(**base)


# --------------------------------------------------------------------------- #
# Escrita — comerciante / admin
# --------------------------------------------------------------------------- #
@router.post(
    "/categories", response_model=CategoryPublic, status_code=status.HTTP_201_CREATED
)
async def create_category(
    payload: CategoryCreate, db: DbSession, _: MerchantOrAdmin
):
    return await catalog_service.create_category(
        db, name=payload.name, slug=payload.slug
    )


@router.post("/stores", response_model=StorePublic, status_code=status.HTTP_201_CREATED)
async def create_store(payload: StoreCreate, db: DbSession, user: CurrentUser):
    if user.role not in (UserRole.MERCHANT, UserRole.ADMIN):
        raise HTTPException(status_code=403, detail="Permissão insuficiente")
    store = await catalog_service.create_store(
        db,
        name=payload.name,
        slug=payload.slug,
        owner_id=user.id,
        latitude=payload.latitude,
        longitude=payload.longitude,
        pix_key=payload.pix_key,
    )
    await log_action(db, action="catalog.store_created", user_id=user.id, entity=str(store.id))
    return store


@router.post(
    "/products", response_model=ProductWithBestPrice, status_code=status.HTTP_201_CREATED
)
async def create_product(payload: ProductCreate, db: DbSession, _: MerchantOrAdmin):
    try:
        product = await catalog_service.create_product(
            db,
            name=payload.name,
            package_size=payload.package_size,
            package_unit=payload.package_unit,
            brand=payload.brand,
            ean=payload.ean,
            image_url=payload.image_url,
            category_id=payload.category_id,
        )
    except UnknownUnitError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return ProductWithBestPrice.model_validate(product)


@router.put(
    "/stores/{store_id}/offers/{product_id}",
    response_model=StoreOffer,
)
async def upsert_offer(
    store_id: uuid.UUID,
    product_id: uuid.UUID,
    payload: OfferUpsert,
    db: DbSession,
    user: CurrentUser,
):
    if user.role not in (UserRole.MERCHANT, UserRole.ADMIN):
        raise HTTPException(status_code=403, detail="Permissão insuficiente")
    from app.models.catalog import Store

    store = await db.get(Store, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="Loja não encontrada")
    # comerciante só edita a própria loja; admin pode tudo
    if user.role == UserRole.MERCHANT and store.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Loja não pertence a você")

    product = await catalog_service.get_product(db, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    offer = await catalog_service.upsert_offer(
        db,
        store_id=store_id,
        product_id=product_id,
        price=payload.price,
        original_price=payload.original_price,
        in_stock=payload.in_stock,
        stock_quantity=payload.stock_quantity,
    )
    from app.core.units import unit_price

    return StoreOffer(
        store_id=store_id,
        store_name=offer.store.name,
        price=float(offer.price),
        original_price=float(offer.original_price) if offer.original_price else None,
        in_stock=offer.in_stock,
        unit_price=unit_price(float(offer.price), product.base_size),
        unit_label=f"R$/{product.base_unit}",
        is_best=False,
    )
