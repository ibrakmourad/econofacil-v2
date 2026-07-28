"""Exporta todos os modelos para que o Alembic detecte o metadata completo."""
from app.models.audit_log import AuditLog
from app.models.base import Base
from app.models.cart import Cart, CartItem, CartStatus
from app.models.catalog import Category, Product, Store, StoreProduct
from app.models.consent import Consent, ConsentPurpose
from app.models.order import Order, OrderFulfillment, OrderItem, OrderStatus
from app.models.payment import Payment, PaymentMethod, PaymentStatus
from app.models.promotion import Promotion, PromotionStatus
from app.models.recipe import Recipe, RecipeIngredient
from app.models.refresh_token import RefreshToken
from app.models.shopping_list import ShoppingList, ShoppingListItem
from app.models.user import User, UserRole

__all__ = [
    "Base",
    "User", "UserRole",
    "RefreshToken",
    "AuditLog",
    "Consent", "ConsentPurpose",
    "Category", "Store", "Product", "StoreProduct",
    "Cart", "CartItem", "CartStatus",
    "Order", "OrderItem", "OrderStatus", "OrderFulfillment",
    "Promotion", "PromotionStatus",
    "Payment", "PaymentMethod", "PaymentStatus",
    "Recipe", "RecipeIngredient",
    "ShoppingList", "ShoppingListItem",
]
