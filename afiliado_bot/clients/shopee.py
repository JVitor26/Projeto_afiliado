from __future__ import annotations

import csv
import hashlib
import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from afiliado_bot.affiliates import apply_affiliate_template
from afiliado_bot.config import AppConfig
from afiliado_bot.models import Product

from .base import ProviderError, retry_http


class ShopeeClient:
    """Shopee connector based on official/exported affiliate feeds.

    Shopee affiliate access can vary by account and region. This connector
    consumes a JSON/CSV feed exported from Shopee or exposed by an official
    Shopee API proxy. It intentionally avoids scraping Shopee pages.
    """

    name = "shopee"

    def __init__(self, config: AppConfig, timeout: int = 20) -> None:
        self.config = config
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(
            (self.config.shopee_app_id and self.config.shopee_app_secret)
            or self.config.shopee_feed_path
            or self.config.shopee_product_feed_url
        )

    def fetch(self, keyword: str, *, limit: int) -> list[Product]:
        if not self.enabled:
            return []

        records = self._load_records(keyword, limit)
        products: list[Product] = []
        keyword_lower = keyword.lower()
        for record in records:
            title = str(record.get("offerName") or record.get("title") or record.get("name") or "").strip()
            category = str(
                record.get("category")
                or record.get("category_name")
                or record.get("categoryId")
                or record.get("collectionId")
                or keyword
            ).strip()
            # A Open API ja pesquisou pela keyword; exigir o termo literal no
            # titulo descartaria acerto legitimo ("air fryer" -> "Fritadeira").
            if not record.get("_from_api"):
                haystack = f"{title} {category}".lower()
                if keyword_lower not in haystack:
                    continue

            external_id = str(
                record.get("offerId")
                or record.get("id")
                or record.get("item_id")
                or record.get("product_id")
                or record.get("offer_id")
                or ""
            )
            affiliate_url = str(
                record.get("offerLink")
                or record.get("affiliate_url")
                or record.get("url")
                or record.get("link")
                or record.get("product_url")
                or ""
            ).strip()
            original_url = str(record.get("originalLink") or record.get("original_url") or affiliate_url).strip()
            if not external_id:
                external_id = _stable_offer_id(record, affiliate_url or original_url or title)
            price = _as_float(record.get("price") or record.get("price_min"))
            if not external_id or not affiliate_url or not title:
                continue

            if not record.get("offerLink"):
                affiliate_url = apply_affiliate_template(
                    self.config.shopee_affiliate_template,
                    affiliate_url,
                    affiliate_id=self.config.shopee_affiliate_id,
                    source=self.name,
                    external_id=external_id,
                )
            commission_rate = _optional_float(record.get("commissionRate"))
            products.append(
                Product(
                    source=self.name,
                    external_id=external_id,
                    title=title,
                    price=price,
                    original_price=_optional_float(record.get("original_price") or record.get("price_before_discount")),
                    currency=str(record.get("currency") or "BRL"),
                    permalink=original_url or affiliate_url,
                    affiliate_url=affiliate_url,
                    image_url=str(record.get("imageUrl") or record.get("image_url") or record.get("image") or ""),
                    category=category,
                    rating=_optional_float(record.get("rating") or record.get("item_rating")),
                    sold_quantity=_optional_int(record.get("sold_quantity") or record.get("historical_sold")),
                    free_shipping=_as_bool(record.get("free_shipping")),
                    metadata={
                        "keyword": keyword,
                        "raw_source": "shopee_offer_v2" if record.get("offerLink") else "shopee_feed",
                        "commission_rate": commission_rate,
                        "offer_type": _optional_int(record.get("offerType")),
                        "category_id": _optional_int(record.get("categoryId")),
                        "collection_id": _optional_int(record.get("collectionId")),
                        "period_start_time": _optional_int(record.get("periodStartTime")),
                        "period_end_time": _optional_int(record.get("periodEndTime")),
                    },
                )
            )
            if len(products) >= limit:
                break
        return products

    def _load_records(self, keyword: str, limit: int) -> list[dict[str, object]]:
        if self.config.shopee_app_id and self.config.shopee_app_secret:
            return self._fetch_open_api(keyword, limit)

        if self.config.shopee_product_feed_url:
            params = urlencode(
                {
                    "keyword": keyword,
                    "sortType": self.config.shopee_sort_type,
                    "page": self.config.shopee_start_page,
                    "limit": limit,
                }
            )
            separator = "&" if "?" in self.config.shopee_product_feed_url else "?"
            url = f"{self.config.shopee_product_feed_url}{separator}{params}"
            headers = {"User-Agent": "afiliado-bot/0.1"}
            if self.config.shopee_authorization_header:
                headers["Authorization"] = self.config.shopee_authorization_header
            request = Request(url, headers=headers)
            try:
                def _do_shopee() -> object:
                    with urlopen(request, timeout=self.timeout) as response:
                        return json.loads(response.read().decode("utf-8"))
                payload = retry_http(_do_shopee)
            except HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                raise ProviderError(f"Shopee feed HTTP {exc.code}: {body[:300]}") from exc
            except URLError as exc:
                raise ProviderError(f"Shopee feed connection error: {exc.reason}") from exc
            return _records_from_payload(payload)

        return self._load_feed_file()

    def _fetch_open_api(self, keyword: str, limit: int) -> list[dict[str, object]]:
        """Consulta productOfferV2 na Open API de afiliados da Shopee."""
        payload = json.dumps(
            {
                "query": _PRODUCT_OFFER_QUERY,
                "variables": {
                    "keyword": keyword,
                    "sortType": self.config.shopee_sort_type,
                    "listType": self.config.shopee_list_type,
                    "page": self.config.shopee_start_page,
                    "limit": max(1, min(limit, 50)),
                },
            },
            separators=(",", ":"),
            ensure_ascii=False,
        )
        timestamp = int(time.time())
        signature = shopee_signature(
            self.config.shopee_app_id, timestamp, payload, self.config.shopee_app_secret
        )
        request = Request(
            self.config.shopee_api_url,
            data=payload.encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "afiliado-bot/0.1",
                "Authorization": (
                    f"SHA256 Credential={self.config.shopee_app_id}, "
                    f"Timestamp={timestamp}, Signature={signature}"
                ),
            },
            method="POST",
        )
        try:
            def _do() -> object:
                with urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            body = retry_http(_do)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ProviderError(f"Shopee Open API HTTP {exc.code}: {detail[:300]}") from exc
        except URLError as exc:
            raise ProviderError(f"Shopee Open API connection error: {exc.reason}") from exc

        # A Shopee responde 200 mesmo em erro; o problema vem em "errors".
        if isinstance(body, dict) and body.get("errors"):
            first = body["errors"][0] if isinstance(body["errors"], list) else body["errors"]
            message = str((first or {}).get("message") or first)
            raise ProviderError(f"Shopee Open API: {message[:300]}")

        nodes = (
            ((body or {}).get("data") or {}).get("productOfferV2") or {}
        ).get("nodes") or []
        return [_record_from_node(node) for node in nodes if isinstance(node, dict)]

    def _load_feed_file(self) -> list[dict[str, object]]:
        path = self.config.shopee_feed_path
        if not path or not path.exists():
            return []
        if path.suffix.lower() == ".csv":
            return _read_csv(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        return _records_from_payload(payload)


_PRODUCT_OFFER_QUERY = """query ($keyword: String, $sortType: Int, $listType: Int, $page: Int, $limit: Int) {
  productOfferV2(keyword: $keyword, sortType: $sortType, listType: $listType, page: $page, limit: $limit) {
    nodes {
      itemId productName price priceMin priceMax priceDiscountRate
      imageUrl productLink offerLink commissionRate commission
      sales ratingStar shopName shopId productCatIds periodStartTime periodEndTime
    }
    pageInfo { page limit hasNextPage }
  }
}"""


def _record_from_node(node: dict[str, object]) -> dict[str, object]:
    """Traduz um no do productOfferV2 para o formato de registro do cliente."""
    price = _as_float(node.get("price") or node.get("priceMin"))
    discount = _as_float(node.get("priceDiscountRate"))
    # A Shopee devolve o preco ja com desconto e a taxa em pontos percentuais;
    # o preco "de" e reconstruido para a mensagem mostrar a economia.
    original = round(price / (1 - discount / 100), 2) if 0 < discount < 100 and price > 0 else None
    categories = node.get("productCatIds")
    category_id = categories[0] if isinstance(categories, list) and categories else None

    return {
        "_from_api": True,
        "offerId": node.get("itemId"),
        "offerName": node.get("productName"),
        "offerLink": node.get("offerLink") or node.get("productLink"),
        "originalLink": node.get("productLink"),
        "price": price,
        "price_before_discount": original,
        "imageUrl": node.get("imageUrl"),
        "category": node.get("shopName") or "",
        "categoryId": category_id,
        "rating": node.get("ratingStar"),
        "sold_quantity": node.get("sales"),
        "commissionRate": node.get("commissionRate"),
        "periodStartTime": node.get("periodStartTime"),
        "periodEndTime": node.get("periodEndTime"),
        "currency": "BRL",
    }


def shopee_signature(app_id: str, timestamp: int, payload: str, secret: str) -> str:
    """Assinatura da Open API: SHA256(appId + timestamp + payload + secret).

    O *payload* precisa ser exatamente o mesmo texto enviado no corpo — por isso
    o JSON e serializado uma vez so e reaproveitado.
    """
    return hashlib.sha256(f"{app_id}{timestamp}{payload}{secret}".encode("utf-8")).hexdigest()


def _records_from_payload(payload: object) -> list[dict[str, object]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("nodes", "products", "items", "offers", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                nested = _records_from_payload(value)
                if nested:
                    return nested
    return []


def _stable_offer_id(record: dict[str, object], fallback: str) -> str:
    offer_type = str(record.get("offerType") or "")
    category_id = str(record.get("categoryId") or "")
    collection_id = str(record.get("collectionId") or "")
    raw = "|".join([offer_type, category_id, collection_id, fallback])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _read_csv(path: Path) -> list[dict[str, object]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def _as_float(value: object) -> float:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def _optional_float(value: object) -> float | None:
    parsed = _as_float(value)
    return parsed if parsed > 0 else None


def _optional_int(value: object) -> int | None:
    try:
        return int(float(str(value).replace(",", ".")))
    except (TypeError, ValueError):
        return None


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes", "sim", "gratis", "free"}
