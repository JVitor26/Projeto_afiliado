from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from afiliado_bot.affiliates import apply_affiliate_template
from afiliado_bot.config import AppConfig
from afiliado_bot.models import Product

from .base import ProviderError


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
        return bool(self.config.shopee_feed_path or self.config.shopee_product_feed_url)

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
                with urlopen(request, timeout=self.timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                raise ProviderError(f"Shopee feed HTTP {exc.code}: {body[:300]}") from exc
            except URLError as exc:
                raise ProviderError(f"Shopee feed connection error: {exc.reason}") from exc
            return _records_from_payload(payload)

        path = self.config.shopee_feed_path
        if not path or not path.exists():
            return []
        if path.suffix.lower() == ".csv":
            return _read_csv(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        return _records_from_payload(payload)


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
