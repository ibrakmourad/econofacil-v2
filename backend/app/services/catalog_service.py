"""Serviço do catálogo: produtos, lojas, ofertas e comparação de preços."""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.units import normalize, unit_price
from app.models.catalog import Category, Product, Store, StoreProduct


# --------------------------------------------------------------------------- #
# Escrita (comerciante / admin)
# --------------------------------------------------------------------------- #
async def create_category(db: AsyncSession, *, name: str, slug: str) -> Category:
    cat = Category(name=name, slug=slug.lower())
    db.add(cat)
    await db.commit()
    await db.refresh(cat)
    return cat


async def create_store(
    db: AsyncSession,
    *,
    name: str,
    slug: str,
    owner_id: uuid.UUID | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    pix_key: str | None = None,
) -> Store:
    store = Store(
        name=name, slug=slug.lower(), owner_id=owner_id,
        latitude=latitude, longitude=longitude, pix_key=pix_key,
    )
    db.add(store)
    await db.commit()
    await db.refresh(store)
    return store


async def create_product(
    db: AsyncSession,
    *,
    name: str,
    package_size: float,
    package_unit: str,
    brand: str | None = None,
    ean: str | None = None,
    image_url: str | None = None,
    category_id: uuid.UUID | None = None,
) -> Product:
    unit_type, base_unit, base_size = normalize(package_size, package_unit)
    product = Product(
        name=name, brand=brand, ean=ean, image_url=image_url,
        category_id=category_id, package_size=package_size,
        package_unit=package_unit, unit_type=unit_type,
        base_unit=base_unit, base_size=base_size,
    )
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return product


async def upsert_offer(
    db: AsyncSession,
    *,
    store_id: uuid.UUID,
    product_id: uuid.UUID,
    price: float,
    original_price: float | None,
    in_stock: bool,
    stock_quantity: int | None = None,
) -> StoreProduct:
    result = await db.execute(
        select(StoreProduct).where(
            StoreProduct.store_id == store_id,
            StoreProduct.product_id == product_id,
        )
    )
    offer = result.scalar_one_or_none()
    if offer is None:
        offer = StoreProduct(
            store_id=store_id, product_id=product_id, price=price,
            original_price=original_price, in_stock=in_stock,
            stock_quantity=stock_quantity,
        )
        db.add(offer)
    else:
        offer.price = price
        offer.original_price = original_price
        offer.in_stock = in_stock
        offer.stock_quantity = stock_quantity
    await db.commit()
    await db.refresh(offer)
    return offer


# --------------------------------------------------------------------------- #
# Leitura (consumidor)
# --------------------------------------------------------------------------- #
async def list_categories(db: AsyncSession) -> list[Category]:
    result = await db.execute(select(Category).order_by(Category.name))
    return list(result.scalars().all())


async def list_products(
    db: AsyncSession,
    *,
    q: str | None = None,
    category_id: uuid.UUID | None = None,
    sort: str = "price",   # "price" | "name"
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    """Lista produtos com o melhor preço unitário e a contagem de lojas.

    Só retorna produtos que possuem ao menos uma oferta em estoque.
    """
    # agrega ofertas em estoque por produto
    offers = (
        select(
            StoreProduct.product_id.label("pid"),
            func.min(StoreProduct.price).label("min_price"),
            func.count(func.distinct(StoreProduct.store_id)).label("store_count"),
        )
        .where(StoreProduct.in_stock.is_(True))
        .group_by(StoreProduct.product_id)
        .subquery()
    )

    stmt = select(Product, offers.c.min_price, offers.c.store_count).join(
        offers, offers.c.pid == Product.id
    )
    if q:
        stmt = stmt.where(Product.name.ilike(f"%{q}%"))
    if category_id:
        stmt = stmt.where(Product.category_id == category_id)

    # total antes da paginação
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    if sort == "name":
        stmt = stmt.order_by(Product.name)
    else:  # menor preço unitário normalizado (RN-001)
        stmt = stmt.order_by(offers.c.min_price / Product.base_size)

    stmt = stmt.limit(page_size).offset((page - 1) * page_size)
    rows = (await db.execute(stmt)).all()

    items: list[dict] = []
    for product, min_price, store_count in rows:
        up = unit_price(float(min_price), product.base_size)
        items.append({
            "product": product,
            "best_unit_price": up,
            "unit_label": f"R$/{product.base_unit}",
            "store_count": int(store_count),
        })
    return items, int(total)


async def get_product(db: AsyncSession, product_id: uuid.UUID) -> Product | None:
    return await db.get(Product, product_id)


async def compare_product(
    db: AsyncSession, product: Product
) -> tuple[list[dict], float | None]:
    """Ofertas do produto ordenadas por preço unitário (a melhor primeiro)."""
    result = await db.execute(
        select(StoreProduct)
        .join(Store, Store.id == StoreProduct.store_id)
        .where(StoreProduct.product_id == product.id, Store.is_active.is_(True))
    )
    raw = list(result.scalars().all())

    offers: list[dict] = []
    for sp in raw:
        offers.append({
            "store_id": sp.store_id,
            "store_name": sp.store.name,
            "price": float(sp.price),
            "original_price": float(sp.original_price) if sp.original_price else None,
            "in_stock": sp.in_stock,
            "unit_price": unit_price(float(sp.price), product.base_size),
            "unit_label": f"R$/{product.base_unit}",
            "is_best": False,
        })

    # ordena por preço unitário; em estoque vem antes em empate de disponibilidade
    offers.sort(key=lambda o: (not o["in_stock"], o["unit_price"]))

    best_unit_price = None
    for o in offers:
        if o["in_stock"]:
            o["is_best"] = True
            best_unit_price = o["unit_price"]
            break

    return offers, best_unit_price
