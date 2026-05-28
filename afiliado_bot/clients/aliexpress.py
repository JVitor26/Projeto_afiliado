from __future__ import annotations

import csv
import hashlib
import hmac
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from afiliado_bot.affiliates import apply_affiliate_template
from afiliado_bot.config import AppConfig
from afiliado_bot.models import Product

from .base import ProviderError


class AliExpressClient:
    """AliExpress connector for official affiliate API responses or exported feeds."""

    name = "aliexpress"
    _method = "aliexpress.affiliate.product.query"

    def __init__(self, config: AppConfig, timeout: int = 20) -> None:
        self.config = config
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(
            self.config.aliexpress_product_feed_url
            or self.config.aliexpress_feed_path
            or (
                self.config.aliexpress_app_key
                and self.config.aliexpress_app_secret
                and self.config.aliexpress_tracking_id
            )
        )

    def fetch(self, keyword: str, *, limit: int) -> list[Product]:
        if not self.enabled:
            return []

        mode = self.config.aliexpress_mode
        if mode == "api" or (
            mode == "auto"
            and self.config.aliexpress_app_key
            and self.config.aliexpress_app_secret
            and self.config.aliexpress_tracking_id
        ):
            return self._fetch_api(keyword, limit)
        if mode in {"auto", "feed"}:
            return self._fetch_feed(keyword, limit)
        return []

    def _fetch_api(self, keyword: str, limit: int) -> list[Product]:
        params = {
            "app_key": self.config.aliexpress_app_key,
            "fields": self.config.aliexpress_fields,
            "format": "json",
            "keywords": keyword,
            "method": self._method,
            "page_no": str(max(1, self.config.aliexpress_start_page)),
            "page_size": str(max(1, min(limit, 50))),
            "sign_method": self.config.aliexpress_sign_method,
            "target_currency": self.config.aliexpress_target_currency,
            "target_language": self.config.aliexpress_target_language,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "tracking_id": self.config.aliexpress_tracking_id,
            "v": "2.0",
        }
        if self.config.aliexpress_ship_to_country:
            params["ship_to_country"] = self.config.aliexpress_ship_to_country
        if self.config.aliexpress_sort:
            params["sort"] = self.config.aliexpress_sort

        params["sign"] = _sign_request(
            params,
            self.config.aliexpress_app_secret,
            self.config.aliexpress_sign_method,
        )
        request = Request(
            f"{self.config.aliexpress_api_url}?{urlencode(params)}",
            headers={"User-Agent": "afiliado-bot/0.1", "Accept": "application/json"},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ProviderError(f"AliExpress API HTTP {exc.code}: {body[:300]}") from exc
        except URLError as exc:
            raise ProviderError(f"AliExpress API connection error: {exc.reason}") from exc
        return self._products_from_records(_records_from_payload(payload), keyword, limit, raw_source="aliexpress_api")

    def _fetch_feed(self, keyword: str, limit: int) -> list[Product]:
        records: list[dict[str, object]]
        if self.config.aliexpress_product_feed_url:
            params = urlencode(
                {
                    "keyword": keyword,
                    "q": keyword,
                    "page": self.config.aliexpress_start_page,
                    "limit": limit,
                    "tracking_id": self.config.aliexpress_tracking_id,
                }
            )
            separator = "&" if "?" in self.config.aliexpress_product_feed_url else "?"
            headers = {"User-Agent": "afiliado-bot/0.1", "Accept": "application/json"}
            if self.config.aliexpress_authorization_header:
                headers["Authorization"] = self.config.aliexpress_authorization_header
            request = Request(f"{self.config.aliexpress_product_feed_url}{separator}{params}", headers=headers)
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                raise ProviderError(f"AliExpress feed HTTP {exc.code}: {body[:300]}") from exc
            except URLError as exc:
                raise ProviderError(f"AliExpress feed connection error: {exc.reason}") from exc
            records = _records_from_payload(payload)
        else:
            path = self.config.aliexpress_feed_path
            if not path or not path.exists():
                return []
            records = _read_csv(path) if path.suffix.lower() == ".csv" else _records_from_payload(
                json.loads(path.read_text(encoding="utf-8"))
            )
        return self._products_from_records(records, keyword, limit, raw_source="aliexpress_feed")

    def _products_from_records(
        self,
        records: list[dict[str, object]],
        keyword: str,
        limit: int,
        *,
        raw_source: str,
    ) -> list[Product]:
        products: list[Product] = []
        keyword_lower = keyword.lower()
        for record in records:
            title = _first_text(
                record,
                "product_title",
                "productTitle",
                "title",
                "name",
                "item_title",
                "subject",
            )
            category = _first_text(
                record,
                "first_level_category_name",
                "second_level_category_name",
                "category_name",
                "category",
                default=keyword,
            )
            haystack = f"{title} {category}".lower()
            if keyword_lower not in haystack:
                continue

            external_id = _first_text(record, "product_id", "productId", "id", "item_id", "itemId", "sku")
            affiliate_url = _first_text(
                record,
                "promotion_link",
                "promotionLink",
                "affiliate_url",
                "affiliateUrl",
                "offerLink",
            )
            permalink = _first_text(
                record,
                "product_detail_url",
                "productDetailUrl",
                "original_url",
                "originalUrl",
                "url",
                "link",
                "product_url",
                default=affiliate_url,
            )
            if not affiliate_url and permalink:
                affiliate_url = apply_affiliate_template(
                    self.config.aliexpress_affiliate_template,
                    permalink,
                    affiliate_id=self.config.aliexpress_tracking_id,
                    source=self.name,
                    external_id=external_id,
                )

            price = _as_float(
                _first_value(
                    record,
                    "target_sale_price",
                    "targetSalePrice",
                    "sale_price",
                    "salePrice",
                    "app_sale_price",
                    "price",
                    "min_sale_price",
                )
            )
            if not external_id or not title or not affiliate_url:
                continue

            commission_rate = _commission_rate(_first_value(record, "commission_rate", "commissionRate"))
            products.append(
                Product(
                    source=self.name,
                    external_id=external_id,
                    title=title,
                    price=price,
                    original_price=_optional_float(
                        _first_value(
                            record,
                            "target_original_price",
                            "targetOriginalPrice",
                            "original_price",
                            "originalPrice",
                            "list_price",
                        )
                    ),
                    currency=_first_text(
                        record,
                        "target_sale_price_currency",
                        "targetSalePriceCurrency",
                        "currency",
                        default=self.config.aliexpress_target_currency,
                    ),
                    permalink=permalink or affiliate_url,
                    affiliate_url=affiliate_url,
                    image_url=_first_text(
                        record,
                        "product_main_image_url",
                        "productMainImageUrl",
                        "image_url",
                        "imageUrl",
                        "image",
                    ),
                    category=category,
                    rating=_rating(_first_value(record, "rating", "stars", "evaluate_rate", "evaluateRate")),
                    sold_quantity=_optional_int(
                        _first_value(
                            record,
                            "lastest_volume",
                            "latest_volume",
                            "sold_quantity",
                            "orders",
                            "volume",
                            "sale_count",
                        )
                    ),
                    free_shipping=_as_bool(_first_value(record, "free_shipping", "freeShipping")),
                    metadata={
                        "keyword": keyword,
                        "raw_source": raw_source,
                        "commission_rate": commission_rate,
                        "discount": _first_text(record, "discount", "discount_rate", "discountRate"),
                        "tracking_id": self.config.aliexpress_tracking_id,
                    },
                )
            )
            if len(products) >= limit:
                break
        return products


def _sign_request(params: dict[str, str], secret: str, sign_method: str) -> str:
    payload = "".join(f"{key}{params[key]}" for key in sorted(params) if key != "sign")
    if sign_method in {"sha256", "hmac", "hmac-sha256"}:
        return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest().upper()
    return hashlib.md5(f"{secret}{payload}{secret}".encode("utf-8")).hexdigest().upper()


def _records_from_payload(payload: object) -> list[dict[str, object]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("products", "product", "items", "offers", "data", "results", "nodes"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                nested = _records_from_payload(value)
                if nested:
                    return nested
        for value in payload.values():
            if isinstance(value, dict):
                nested = _records_from_payload(value)
                if nested:
                    return nested
    return []


def _read_csv(path: Path) -> list[dict[str, object]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def _first_value(record: dict[str, object], *keys: str) -> object:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return None


def _first_text(record: dict[str, object], *keys: str, default: str = "") -> str:
    value = _first_value(record, *keys)
    if value in (None, ""):
        return default
    return str(value).strip()


def _as_float(value: object) -> float:
    if value is None:
        return 0.0
    text = re.sub(r"[^0-9,.\-]", "", str(value).strip())
    if not text:
        return 0.0
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return 0.0


def _optional_float(value: object) -> float | None:
    parsed = _as_float(value)
    return parsed if parsed > 0 else None


def _optional_int(value: object) -> int | None:
    parsed = _as_float(value)
    return int(parsed) if parsed > 0 else None


def _commission_rate(value: object) -> float | None:
    parsed = _as_float(value)
    if parsed <= 0:
        return None
    return parsed / 100 if parsed > 1 else parsed


def _rating(value: object) -> float | None:
    parsed = _as_float(value)
    if parsed <= 0:
        return None
    if parsed > 5:
        return min(parsed / 20, 5)
    return parsed


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes", "sim", "gratis", "free", "frete gratis"}
