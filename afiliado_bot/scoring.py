from __future__ import annotations

import math

from .config import AppConfig
from .models import Product


class ProductRanker:
    def __init__(self, config: AppConfig, category_boosts: dict[str, float] | None = None) -> None:
        self.config = config
        self.category_boosts = category_boosts or {}

    def reject_reason(self, product: Product) -> str | None:
        title = product.title.lower()
        for denied in self.config.deny_keywords:
            if denied.lower() in title:
                return f"blocked keyword: {denied}"

        if self.config.require_product_image and not product.image_url.strip():
            return "missing product image"

        url_text = f"{product.permalink} {product.affiliate_url}".lower()
        if any(marker in url_text for marker in ("example.com", "produto-demo", "oferta-afiliada-demo", "demo-shopee")):
            return "demo or example link"

        if product.sold_quantity is not None and product.sold_quantity < self.config.min_sold_quantity:
            return f"sold quantity below minimum ({product.sold_quantity} < {self.config.min_sold_quantity})"

        seller_transactions_value = product.metadata.get("seller_completed_transactions")
        seller_transactions = _as_int(seller_transactions_value)
        if seller_transactions_value is not None and seller_transactions < self.config.min_seller_transactions:
            return (
                "seller transactions below minimum "
                f"({seller_transactions} < {self.config.min_seller_transactions})"
            )

        if self.config.min_price and product.price < self.config.min_price:
            return "price below minimum"
        if self.config.max_price and product.price > self.config.max_price:
            return "price above maximum"
        if (
            self.config.min_discount_percent
            and product.discount_percent
            and product.discount_percent < self.config.min_discount_percent
        ):
            return "discount below minimum"
        return None

    def score(self, product: Product) -> float:
        score = 25.0 if product.price <= 0 else 10.0
        score += min(product.discount_percent * 1.8, 45.0)
        commission_rate = _as_float(product.metadata.get("commission_rate"))
        if commission_rate:
            score += min(commission_rate * 100 * 2.5, 22.0)

        if product.sold_quantity:
            score += min(math.log10(product.sold_quantity + 1) * 10, 28.0)
        seller_transactions = _as_int(product.metadata.get("seller_completed_transactions"))
        if seller_transactions:
            score += min(math.log10(seller_transactions + 1) * 8, 24.0)
        if product.metadata.get("seller_power_seller_status"):
            score += 8
        if product.metadata.get("official_store_id"):
            score += 8
        if product.rating:
            score += max(product.rating - 3.5, 0) * 8
        if product.free_shipping:
            score += 7

        title = product.title.lower()
        if any(term in title for term in ("oferta", "promocao", "promoção", "desconto")):
            score += 4

        if product.category:
            score += min(self.category_boosts.get(product.category, 0), 18)

        if product.original_price and product.original_price > product.price:
            score += 5

        return round(score, 2)


def _as_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _as_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
