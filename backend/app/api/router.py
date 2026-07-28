"""Agregador de rotas da API v1."""
from fastapi import APIRouter

from app.api.v1 import (
    admin, auth, cart, catalog, lgpd, lists, merchant, noor, orders, payments, recipes, users,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(lgpd.router)
api_router.include_router(catalog.router)
api_router.include_router(cart.router)
api_router.include_router(orders.router)
api_router.include_router(noor.router)
api_router.include_router(merchant.router)
api_router.include_router(payments.router)
api_router.include_router(recipes.router)
api_router.include_router(lists.router)
api_router.include_router(admin.router)
