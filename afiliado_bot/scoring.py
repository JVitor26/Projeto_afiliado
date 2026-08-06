from __future__ import annotations

import math

from .config import AppConfig
from .models import Product

_BROKEN_SCRAPE_MARKERS = (
    "não foi possível", "nao foi possivel", "página não encontrada", "pagina nao encontrada",
    "page not found", "404 not found", "acesso negado", "access denied",
)

_TRUSTED_STORES = frozenset({
    "magazine luiza", "magazineluiza", "magalu",
    "casas bahia", "casasbahia",
    "americanas", "lojas americanas",
    "submarino", "shoptime", "extra", "pontofrio", "ponto frio",
    "carrefour", "kabum",
    "dell", "acer", "samsung", "apple", "lg", "lenovo", "positivo", "multilaser",
    "philips", "tramontina", "mondial", "arno", "brastemp", "consul", "electrolux",
    "sony", "jbl", "bose", "motorola", "xiaomi", "intelbras",
})


class ProductRanker:
    def __init__(self, config: AppConfig, category_boosts: dict[str, float] | None = None) -> None:
        self.config = config
        self.category_boosts = category_boosts or {}

    def reject_reason(self, product: Product) -> str | None:
        title = product.title.lower()
        for denied in self.config.deny_keywords:
            if denied.lower() in title:
                return f"blocked keyword: {denied}"

        if any(marker in title for marker in _BROKEN_SCRAPE_MARKERS):
            return "broken page title (scrape failure)"

        if self.config.require_product_image and not product.image_url.strip():
            return "missing product image"

        url_text = f"{product.permalink} {product.affiliate_url}".lower()
        if any(marker in url_text for marker in ("example.com", "produto-demo", "oferta-afiliada-demo", "demo-shopee")):
            return "demo or example link"

        if product.price <= 0:
            coupon_code = str(product.metadata.get("coupon_code") or "").strip()
            search_code = str(product.metadata.get("search_code") or "").strip()
            if not coupon_code and not search_code:
                return "no price and no coupon/search code (likely broken scrape)"

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
            and product.original_price is not None
            and product.discount_percent < self.config.min_discount_percent
        ):
            return "discount below minimum"
        return None

    def score(self, product: Product) -> float:
        score = 25.0 if product.price <= 0 else 10.0
        score += min(product.discount_percent * 2.0, 50.0)
        commission_rate = _as_float(product.metadata.get("commission_rate"))
        if commission_rate:
            score += min(commission_rate * 100 * 2.5, 22.0)

        # Bônus por ticket alto (produtos acima de R$300 geram mais comissão)
        if product.price >= 1000:
            score += 12
        elif product.price >= 300:
            score += 6

        if product.sold_quantity:
            score += min(math.log10(product.sold_quantity + 1) * 12, 32.0)
        seller_transactions = _as_int(product.metadata.get("seller_completed_transactions"))
        if seller_transactions:
            score += min(math.log10(seller_transactions + 1) * 8, 24.0)
        if product.metadata.get("seller_power_seller_status"):
            score += 8
        if product.metadata.get("official_store_id"):
            score += 8
        if product.rating:
            score += max(product.rating - 3.5, 0) * 10
        if product.free_shipping:
            score += 8

        # Bonus: lojas confiáveis (Magazine Luiza, Casas Bahia, Dell, Acer, etc.)
        store_name = str(product.metadata.get("official_store_name") or "").lower().strip()
        if store_name and any(t in store_name for t in _TRUSTED_STORES):
            score += 15

        # Bonus: ofertas relâmpago e ofertas do dia
        offer_type = str(product.metadata.get("offer_type") or "").lower()
        flash_by_type = any(t in offer_type for t in ("flash", "relamp", "lightning", "deal_of_day"))
        daily_by_type = any(t in offer_type for t in ("dia", "daily", "day"))
        title_lower = product.title.lower()
        flash_in_title = any(t in title_lower for t in ("relâmpago", "relampago", "oferta do dia", "oferta dia"))

        if flash_by_type or flash_in_title:
            score += 20
        elif daily_by_type:
            score += 12

        # Bonus: oferta com prazo (period_end_time preenchido)
        if str(product.metadata.get("period_end_time") or "").strip():
            score += 8

        # Bonus genérico de promoção (só se não for flash/daily já contado)
        if not flash_by_type and not flash_in_title and not daily_by_type:
            if any(t in title_lower for t in ("oferta", "promocao", "promoção", "desconto")):
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
