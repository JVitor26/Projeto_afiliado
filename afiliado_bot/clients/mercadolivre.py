from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from afiliado_bot.affiliates import apply_affiliate_template
from afiliado_bot.config import AppConfig
from afiliado_bot.models import Product

from .base import ProviderError


class MercadoLivreClient:
    name = "mercadolivre"

    def __init__(self, config: AppConfig, timeout: int = 20) -> None:
        self.config = config
        self.timeout = timeout

    def fetch(self, keyword: str, *, limit: int) -> list[Product]:
        params: dict[str, object] = {
            "q": keyword,
            "limit": max(1, min(limit, 50)),
        }
        if self.config.mercadolivre_min_discount > 0:
            params["discount"] = f"{self.config.mercadolivre_min_discount}-100"
        url = (
            f"https://api.mercadolibre.com/sites/"
            f"{self.config.mercadolivre_site_id}/search?{urlencode(params)}"
        )
        try:
            payload = self._fetch_search_payload(url)
        except ProviderError as exc:
            if "HTTP 403" not in str(exc):
                raise
            return self._fetch_catalog_products(keyword, limit=limit)

        products: list[Product] = []
        for item in payload.get("results", []):
            permalink = item.get("permalink") or ""
            external_id = str(item.get("id") or "")
            if not permalink or not external_id:
                continue

            price = _as_float(item.get("price"))
            if price <= 0:
                continue

            affiliate_url = apply_affiliate_template(
                self.config.mercadolivre_affiliate_template,
                permalink,
                affiliate_id=self.config.mercadolivre_affiliate_id,
                source=self.name,
                external_id=external_id,
            )
            shipping = item.get("shipping") or {}
            installments = item.get("installments") or {}
            product = Product(
                source=self.name,
                external_id=external_id,
                title=item.get("title") or "Produto Mercado Livre",
                price=price,
                original_price=_optional_float(item.get("original_price")),
                currency=item.get("currency_id") or "BRL",
                permalink=permalink,
                affiliate_url=affiliate_url,
                image_url=item.get("thumbnail") or "",
                category=item.get("category_id") or keyword,
                rating=_optional_float((item.get("reviews") or {}).get("rating_average")),
                sold_quantity=_optional_int(item.get("sold_quantity")),
                free_shipping=bool(shipping.get("free_shipping")),
                metadata={
                    "keyword": keyword,
                    "condition": item.get("condition"),
                    "seller_id": (item.get("seller") or {}).get("id"),
                    "installments": installments,
                    "official_store_id": item.get("official_store_id"),
                    "official_store_name": item.get("official_store_name"),
                },
            )
            self._enrich_product_quality(product)
            products.append(product)
        return products or self._fetch_catalog_products(keyword, limit=limit)

    def _fetch_catalog_products(self, keyword: str, *, limit: int) -> list[Product]:
        if not self.config.mercadolivre_access_token:
            raise ProviderError("Mercado Livre HTTP 403: search bloqueado e sem access token para products/search")

        params = {
            "status": "active",
            "site_id": self.config.mercadolivre_site_id,
            "q": keyword,
            "limit": max(1, min(limit, 20)),
        }
        url = f"https://api.mercadolibre.com/products/search?{urlencode(params)}"
        try:
            payload = self._fetch_json(url, use_token=True)
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ProviderError(f"Mercado Livre catalog HTTP {exc.code}: {body[:300]}") from exc
        except URLError as exc:
            raise ProviderError(f"Mercado Livre catalog connection error: {exc.reason}") from exc

        products: list[Product] = []
        for catalog in payload.get("results", []):
            if not isinstance(catalog, dict):
                continue
            catalog_id = str(catalog.get("id") or catalog.get("catalog_product_id") or "")
            if not catalog_id:
                continue
            try:
                item = self._best_catalog_item(catalog_id)
            except ProviderError:
                continue
            if not item:
                continue

            external_id = str(item.get("item_id") or "")
            price = _as_float(item.get("price"))
            if not external_id or price <= 0:
                continue

            permalink = _item_permalink(external_id)
            affiliate_url = apply_affiliate_template(
                self.config.mercadolivre_affiliate_template,
                permalink,
                affiliate_id=self.config.mercadolivre_affiliate_id,
                source=self.name,
                external_id=external_id,
            )
            shipping = item.get("shipping") or {}
            original_price = _optional_float(item.get("original_price"))
            if original_price and original_price <= price:
                original_price = None

            product = Product(
                source=self.name,
                external_id=external_id,
                title=str(catalog.get("name") or "Produto Mercado Livre"),
                price=price,
                original_price=original_price,
                currency=str(item.get("currency_id") or "BRL"),
                permalink=permalink,
                affiliate_url=affiliate_url,
                image_url=_catalog_image(catalog),
                category=str(item.get("category_id") or catalog.get("domain_id") or keyword),
                sold_quantity=_optional_int(item.get("sold_quantity")),
                free_shipping=bool(shipping.get("free_shipping")),
                metadata={
                    "keyword": keyword,
                    "condition": item.get("condition"),
                    "seller_id": item.get("seller_id"),
                    "catalog_product_id": catalog_id,
                    "raw_source": "mercadolivre_catalog_search",
                    "official_store_id": item.get("official_store_id"),
                    "official_store_name": item.get("official_store_name"),
                },
            )
            self._enrich_product_quality(product)
            products.append(product)
            if len(products) >= limit:
                break
        return products

    def _best_catalog_item(self, catalog_id: str) -> dict[str, object] | None:
        params = {"limit": 5}
        url = f"https://api.mercadolibre.com/products/{catalog_id}/items?{urlencode(params)}"
        try:
            payload = self._fetch_json(url, use_token=True)
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ProviderError(f"Mercado Livre catalog items HTTP {exc.code}: {body[:300]}") from exc
        except URLError as exc:
            raise ProviderError(f"Mercado Livre catalog items connection error: {exc.reason}") from exc

        items = [item for item in payload.get("results", []) if isinstance(item, dict) and _as_float(item.get("price")) > 0]
        if not items:
            return None
        return max(items, key=_catalog_item_rank)

    def _fetch_search_payload(self, url: str) -> dict[str, object]:
        try:
            return self._fetch_json(url, use_token=bool(self.config.mercadolivre_access_token))
        except HTTPError as exc:
            if self.config.mercadolivre_access_token and exc.code in {401, 403}:
                try:
                    return self._fetch_json(url, use_token=False)
                except HTTPError as public_exc:
                    body = public_exc.read().decode("utf-8", errors="replace")
                    raise ProviderError(f"Mercado Livre HTTP {public_exc.code}: {body[:300]}") from public_exc
            body = exc.read().decode("utf-8", errors="replace")
            raise ProviderError(f"Mercado Livre HTTP {exc.code}: {body[:300]}") from exc
        except URLError as exc:
            raise ProviderError(f"Mercado Livre connection error: {exc.reason}") from exc

    def _enrich_product_quality(self, product: Product) -> None:
        item = self._safe_fetch_json(
            f"https://api.mercadolibre.com/items/{product.external_id}",
            use_token=bool(self.config.mercadolivre_access_token),
        )
        if item:
            product.sold_quantity = _optional_int(item.get("sold_quantity")) or product.sold_quantity
            product.image_url = _item_image(item) or product.image_url
            product.rating = _optional_float((item.get("reviews") or {}).get("rating_average")) or product.rating
            if item.get("seller_id"):
                product.metadata["seller_id"] = item.get("seller_id")
            if item.get("official_store_id"):
                product.metadata["official_store_id"] = item.get("official_store_id")
            if item.get("official_store_name"):
                product.metadata["official_store_name"] = item.get("official_store_name")

        seller_id = product.metadata.get("seller_id")
        if not seller_id:
            return

        seller = self._safe_fetch_json(
            f"https://api.mercadolibre.com/users/{seller_id}",
            use_token=bool(self.config.mercadolivre_access_token),
        )
        if not seller:
            return

        product.metadata["seller_nickname"] = seller.get("nickname") or ""
        reputation = seller.get("seller_reputation") or {}
        if not isinstance(reputation, dict):
            return
        transactions = reputation.get("transactions") or {}
        if isinstance(transactions, dict):
            completed = _optional_int(transactions.get("completed"))
            total = _optional_int(transactions.get("total"))
            if completed is not None:
                product.metadata["seller_completed_transactions"] = completed
            if total is not None:
                product.metadata["seller_total_transactions"] = total
        product.metadata["seller_power_seller_status"] = reputation.get("power_seller_status") or ""
        product.metadata["seller_level_id"] = reputation.get("level_id") or ""

    def _safe_fetch_json(self, url: str, *, use_token: bool) -> dict[str, object]:
        try:
            return self._fetch_json(url, use_token=use_token)
        except HTTPError as exc:
            if use_token and exc.code in {401, 403}:
                try:
                    return self._fetch_json(url, use_token=False)
                except (HTTPError, URLError, json.JSONDecodeError, ProviderError):
                    return {}
            return {}
        except (URLError, json.JSONDecodeError, ProviderError):
            return {}

    def _fetch_json(self, url: str, *, use_token: bool) -> dict[str, object]:
        headers = {"User-Agent": "afiliado-bot/0.1", "Accept": "application/json"}
        if use_token:
            headers["Authorization"] = f"Bearer {self.config.mercadolivre_access_token}"
        request = Request(url, headers=headers)
        with urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ProviderError("Mercado Livre retornou resposta invalida")
        return payload


def _as_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _optional_float(value: object) -> float | None:
    parsed = _as_float(value)
    return parsed if parsed > 0 else None


def _optional_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _catalog_item_rank(item: dict[str, object]) -> tuple[float, float, float, float]:
    price = _as_float(item.get("price"))
    original_price = _as_float(item.get("original_price"))
    discount = 0.0
    if original_price > price > 0:
        discount = (original_price - price) / original_price
    shipping = item.get("shipping") or {}
    free_shipping = 1.0 if isinstance(shipping, dict) and shipping.get("free_shipping") else 0.0
    sold_quantity = float(_optional_int(item.get("sold_quantity")) or 0)
    return sold_quantity, free_shipping, discount, -price


def _item_permalink(item_id: str) -> str:
    match = item_id.upper().replace("-", "")
    if match.startswith("MLB"):
        return f"https://produto.mercadolivre.com.br/MLB-{match[3:]}"
    return f"https://produto.mercadolivre.com.br/{item_id}"


def _catalog_image(catalog: dict[str, object]) -> str:
    pictures = catalog.get("pictures")
    if isinstance(pictures, list) and pictures and isinstance(pictures[0], dict):
        return str(pictures[0].get("secure_url") or pictures[0].get("url") or "")
    return ""


def _item_image(item: dict[str, object]) -> str:
    pictures = item.get("pictures")
    if isinstance(pictures, list) and pictures and isinstance(pictures[0], dict):
        return str(pictures[0].get("secure_url") or pictures[0].get("url") or "")
    return str(item.get("secure_thumbnail") or item.get("thumbnail") or "")
