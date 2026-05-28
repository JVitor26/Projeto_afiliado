from __future__ import annotations

import csv
import base64
import hashlib
import hmac
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from afiliado_bot.affiliates import apply_affiliate_template
from afiliado_bot.config import AppConfig
from afiliado_bot.models import Product

from .base import ProviderError


class AmazonClient:
    """Amazon connector using official/API feeds and optional PA-API legacy signing."""

    name = "amazon"
    _paapi_target = "com.amazon.paapi5.v1.ProductAdvertisingAPIv1.SearchItems"
    _paapi_path = "/paapi5/searchitems"
    _service = "ProductAdvertisingAPI"

    def __init__(self, config: AppConfig, timeout: int = 20) -> None:
        self.config = config
        self.timeout = timeout
        self._creators_token = ""
        self._creators_token_expires_at = datetime.min.replace(tzinfo=timezone.utc)

    @property
    def enabled(self) -> bool:
        return bool(
            self.config.amazon_creators_api_url
            or (
                self.config.amazon_creators_credential_id
                and self.config.amazon_creators_credential_secret
                and self.config.amazon_partner_tag
            )
            or self.config.amazon_product_feed_url
            or self.config.amazon_feed_path
            or (
                self.config.amazon_access_key
                and self.config.amazon_secret_key
                and self.config.amazon_partner_tag
            )
        )

    def fetch(self, keyword: str, *, limit: int) -> list[Product]:
        mode = self.config.amazon_mode
        if mode == "creators" or (
            mode == "auto"
            and (
                self.config.amazon_creators_api_url
                or (
                    self.config.amazon_creators_credential_id
                    and self.config.amazon_creators_credential_secret
                    and self.config.amazon_partner_tag
                )
            )
        ):
            return self._fetch_creators_api(keyword, limit)
        if mode == "paapi" or (
            mode == "auto"
            and self.config.amazon_access_key
            and self.config.amazon_secret_key
            and self.config.amazon_partner_tag
        ):
            return self._fetch_paapi(keyword, limit)
        if mode in {"auto", "feed"}:
            return self._fetch_feed(keyword, limit)
        return []

    def _fetch_creators_api(self, keyword: str, limit: int) -> list[Product]:
        if self._official_creators_enabled:
            return self._fetch_official_creators_api(keyword, limit)

        url = self.config.amazon_creators_api_url
        params = urlencode({"keywords": keyword, "limit": max(1, min(limit, 10))})
        separator = "&" if "?" in url else "?"
        headers = {"User-Agent": "afiliado-bot/0.1", "Accept": "application/json"}
        if self.config.amazon_authorization_header:
            headers["Authorization"] = self.config.amazon_authorization_header
        request = Request(f"{url}{separator}{params}", headers=headers)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ProviderError(f"Amazon Creators API HTTP {exc.code}: {body[:300]}") from exc
        except URLError as exc:
            raise ProviderError(f"Amazon Creators API connection error: {exc.reason}") from exc
        return self._products_from_records(_records_from_payload(payload), keyword, limit)

    @property
    def _official_creators_enabled(self) -> bool:
        return bool(
            self.config.amazon_creators_credential_id
            and self.config.amazon_creators_credential_secret
            and self.config.amazon_partner_tag
        )

    def _fetch_official_creators_api(self, keyword: str, limit: int) -> list[Product]:
        item_count = max(1, min(limit, 10))
        payload = {
            "keywords": keyword,
            "itemCount": item_count,
            "partnerTag": self.config.amazon_partner_tag,
            "partnerType": self.config.amazon_partner_type,
            "marketplace": self.config.amazon_marketplace,
            "resources": [
                "browseNodeInfo.browseNodes",
                "images.primary.large",
                "itemInfo.title",
                "offersV2.listings.price",
                "offersV2.listings.savingBasis",
                "offersV2.listings.deliveryInfo.isFreeShippingEligible",
                "customerReviews.count",
                "customerReviews.starRating",
            ],
        }
        request = Request(
            "https://creatorsapi.amazon/catalog/v1/searchItems",
            data=json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": self._creators_authorization_header(),
                "Content-Type": "application/json",
                "Accept": "application/json",
                "x-marketplace": self.config.amazon_marketplace,
                "User-Agent": "afiliado-bot/0.1",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ProviderError(f"Amazon Creators API HTTP {exc.code}: {body[:300]}") from exc
        except URLError as exc:
            raise ProviderError(f"Amazon Creators API connection error: {exc.reason}") from exc

        items = (
            _deep_value_any(response_payload, ("searchResult", "items"))
            or _deep_value_any(response_payload, ("SearchResult", "Items"))
            or []
        )
        if not isinstance(items, list):
            return []
        return self._products_from_creators_items(items, keyword)

    def _creators_authorization_header(self) -> str:
        token = self._creators_access_token()
        version = self.config.amazon_creators_version.strip()
        if version.startswith("2."):
            return f"Bearer {token}, Version {version}"
        return f"Bearer {token}"

    def _creators_access_token(self) -> str:
        now = datetime.now(timezone.utc)
        if self._creators_token and self._creators_token_expires_at > now + timedelta(minutes=2):
            return self._creators_token

        version = self.config.amazon_creators_version.strip() or "3.1"
        token_url = self.config.amazon_creators_token_url or _creators_token_url(version)
        request = _creators_token_request(
            token_url,
            version,
            self.config.amazon_creators_credential_id,
            self.config.amazon_creators_credential_secret,
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ProviderError(f"Amazon Creators token HTTP {exc.code}: {body[:300]}") from exc
        except URLError as exc:
            raise ProviderError(f"Amazon Creators token connection error: {exc.reason}") from exc

        token = str(payload.get("access_token") or "").strip()
        if not token:
            raise ProviderError("Amazon Creators token sem access_token")
        expires_in = _optional_int(payload.get("expires_in")) or 3600
        self._creators_token = token
        self._creators_token_expires_at = now + timedelta(seconds=max(expires_in - 60, 60))
        return token

    def _fetch_paapi(self, keyword: str, limit: int) -> list[Product]:
        item_count = max(1, min(limit, 10))
        payload = {
            "Keywords": keyword,
            "ItemCount": item_count,
            "PartnerTag": self.config.amazon_partner_tag,
            "PartnerType": self.config.amazon_partner_type,
            "Marketplace": self.config.amazon_marketplace,
            "SearchIndex": self.config.amazon_search_index,
            "Resources": [
                "BrowseNodeInfo.BrowseNodes",
                "Images.Primary.Large",
                "ItemInfo.Title",
                "Offers.Listings.Price",
                "Offers.Listings.SavingBasis",
                "Offers.Listings.DeliveryInfo.IsFreeShippingEligible",
                "CustomerReviews.Count",
                "CustomerReviews.StarRating",
            ],
        }
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        headers = self._signed_headers(body)
        request = Request(
            f"https://{self.config.amazon_host}{self._paapi_path}",
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            raise ProviderError(f"Amazon PA-API HTTP {exc.code}: {body_text[:300]}") from exc
        except URLError as exc:
            raise ProviderError(f"Amazon PA-API connection error: {exc.reason}") from exc

        items = (response_payload.get("SearchResult") or {}).get("Items") or []
        return self._products_from_paapi_items(items, keyword)

    def _fetch_feed(self, keyword: str, limit: int) -> list[Product]:
        records: list[dict[str, object]]
        if self.config.amazon_product_feed_url:
            params = urlencode({"q": keyword, "limit": limit})
            separator = "&" if "?" in self.config.amazon_product_feed_url else "?"
            headers = {"User-Agent": "afiliado-bot/0.1", "Accept": "application/json"}
            if self.config.amazon_authorization_header:
                headers["Authorization"] = self.config.amazon_authorization_header
            request = Request(f"{self.config.amazon_product_feed_url}{separator}{params}", headers=headers)
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                raise ProviderError(f"Amazon feed HTTP {exc.code}: {body[:300]}") from exc
            except URLError as exc:
                raise ProviderError(f"Amazon feed connection error: {exc.reason}") from exc
            records = _records_from_payload(payload)
        else:
            path = self.config.amazon_feed_path
            if not path or not path.exists():
                return []
            records = _read_csv(path) if path.suffix.lower() == ".csv" else _records_from_payload(
                json.loads(path.read_text(encoding="utf-8"))
            )
        return self._products_from_records(records, keyword, limit)

    def _products_from_paapi_items(self, items: list[dict[str, object]], keyword: str) -> list[Product]:
        products: list[Product] = []
        for item in items:
            asin = str(item.get("ASIN") or "")
            detail_url = str(item.get("DetailPageURL") or "")
            title = _deep_value(item, ("ItemInfo", "Title", "DisplayValue")) or "Produto Amazon"
            listing = _first(_deep_value(item, ("Offers", "Listings")) or [])
            price = _as_float(_deep_value(listing, ("Price", "Amount")))
            if not asin or not detail_url or price <= 0:
                continue

            original_price = _optional_float(_deep_value(listing, ("SavingBasis", "Amount")))
            browse_node = _first(_deep_value(item, ("BrowseNodeInfo", "BrowseNodes")) or [])
            image_url = (
                _deep_value(item, ("Images", "Primary", "Large", "URL"))
                or _deep_value(item, ("Images", "Primary", "Medium", "URL"))
                or ""
            )
            products.append(
                Product(
                    source=self.name,
                    external_id=asin,
                    title=str(title),
                    price=price,
                    original_price=original_price,
                    currency=str(_deep_value(listing, ("Price", "Currency")) or "BRL"),
                    permalink=detail_url,
                    affiliate_url=detail_url,
                    image_url=str(image_url),
                    category=str(_deep_value(browse_node, ("DisplayName",)) or keyword),
                    rating=_optional_float(_deep_value(item, ("CustomerReviews", "StarRating", "Value"))),
                    sold_quantity=_optional_int(_deep_value(item, ("CustomerReviews", "Count"))),
                    free_shipping=bool(
                        _deep_value(listing, ("DeliveryInfo", "IsFreeShippingEligible"))
                    ),
                    metadata={"keyword": keyword, "raw_source": "amazon_paapi"},
                )
            )
        return products

    def _products_from_creators_items(self, items: list[dict[str, object]], keyword: str) -> list[Product]:
        products: list[Product] = []
        for item in items:
            asin = str(_deep_value_any(item, ("asin",)) or _deep_value_any(item, ("ASIN",)) or "")
            detail_url = str(
                _deep_value_any(item, ("detailPageURL",))
                or _deep_value_any(item, ("detailPageUrl",))
                or _deep_value_any(item, ("DetailPageURL",))
                or (f"https://{self.config.amazon_marketplace}/dp/{asin}" if asin else "")
            )
            title = (
                _deep_value_any(item, ("itemInfo", "title", "displayValue"))
                or _deep_value_any(item, ("ItemInfo", "Title", "DisplayValue"))
                or "Produto Amazon"
            )
            listing = _first(
                _deep_value_any(item, ("offersV2", "listings"))
                or _deep_value_any(item, ("OffersV2", "Listings"))
                or []
            )
            price = _as_float(
                _deep_value_any(listing, ("price", "amount"))
                or _deep_value_any(listing, ("Price", "Amount"))
                or _deep_value_any(listing, ("price", "displayAmount"))
            )
            if not asin or not detail_url or price <= 0:
                continue

            original_price = _optional_float(
                _deep_value_any(listing, ("savingBasis", "amount"))
                or _deep_value_any(listing, ("SavingBasis", "Amount"))
                or _deep_value_any(listing, ("savingBasis", "displayAmount"))
            )
            browse_node = _first(
                _deep_value_any(item, ("browseNodeInfo", "browseNodes"))
                or _deep_value_any(item, ("BrowseNodeInfo", "BrowseNodes"))
                or []
            )
            image_url = (
                _deep_value_any(item, ("images", "primary", "large", "url"))
                or _deep_value_any(item, ("Images", "Primary", "Large", "URL"))
                or _deep_value_any(item, ("images", "primary", "medium", "url"))
                or ""
            )
            currency = str(
                _deep_value_any(listing, ("price", "currency"))
                or _deep_value_any(listing, ("Price", "Currency"))
                or "BRL"
            )
            products.append(
                Product(
                    source=self.name,
                    external_id=asin,
                    title=str(title),
                    price=price,
                    original_price=original_price,
                    currency=currency,
                    permalink=detail_url,
                    affiliate_url=apply_affiliate_template(
                        self.config.amazon_affiliate_template,
                        detail_url,
                        affiliate_id=self.config.amazon_partner_tag,
                        source=self.name,
                        external_id=asin,
                    ),
                    image_url=str(image_url),
                    category=str(
                        _deep_value_any(browse_node, ("displayName",))
                        or _deep_value_any(browse_node, ("DisplayName",))
                        or keyword
                    ),
                    rating=_optional_float(
                        _deep_value_any(item, ("customerReviews", "starRating", "value"))
                        or _deep_value_any(item, ("CustomerReviews", "StarRating", "Value"))
                    ),
                    sold_quantity=_optional_int(
                        _deep_value_any(item, ("customerReviews", "count"))
                        or _deep_value_any(item, ("CustomerReviews", "Count"))
                    ),
                    free_shipping=bool(
                        _deep_value_any(listing, ("deliveryInfo", "isFreeShippingEligible"))
                        or _deep_value_any(listing, ("DeliveryInfo", "IsFreeShippingEligible"))
                    ),
                    metadata={"keyword": keyword, "raw_source": "amazon_creators_api"},
                )
            )
        return products

    def _products_from_records(
        self,
        records: list[dict[str, object]],
        keyword: str,
        limit: int,
    ) -> list[Product]:
        products: list[Product] = []
        keyword_lower = keyword.lower()
        for record in records:
            title = str(record.get("title") or record.get("name") or record.get("item_title") or "").strip()
            category = str(record.get("category") or record.get("category_name") or keyword).strip()
            haystack = f"{title} {category}".lower()
            if keyword_lower not in haystack:
                continue

            external_id = str(record.get("asin") or record.get("id") or record.get("product_id") or "").strip()
            url = str(
                record.get("affiliate_url")
                or record.get("url")
                or record.get("link")
                or record.get("product_url")
                or ""
            ).strip()
            price = _as_float(record.get("price") or record.get("amount") or record.get("offer_price"))
            if not external_id or not url or price <= 0:
                continue

            affiliate_url = apply_affiliate_template(
                self.config.amazon_affiliate_template,
                url,
                affiliate_id=self.config.amazon_partner_tag,
                source=self.name,
                external_id=external_id,
            )
            products.append(
                Product(
                    source=self.name,
                    external_id=external_id,
                    title=title,
                    price=price,
                    original_price=_optional_float(record.get("original_price") or record.get("list_price")),
                    currency=str(record.get("currency") or "BRL"),
                    permalink=url,
                    affiliate_url=affiliate_url,
                    image_url=str(record.get("image_url") or record.get("image") or ""),
                    category=category,
                    rating=_optional_float(record.get("rating") or record.get("stars")),
                    sold_quantity=_optional_int(record.get("sold_quantity") or record.get("review_count")),
                    free_shipping=_as_bool(record.get("free_shipping") or record.get("prime")),
                    metadata={"keyword": keyword, "raw_source": "amazon_feed"},
                )
            )
            if len(products) >= limit:
                break
        return products

    def _signed_headers(self, body: bytes) -> dict[str, str]:
        now = datetime.now(timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        content_type = "application/json; charset=utf-8"
        canonical_headers = (
            "content-encoding:amz-1.0\n"
            f"content-type:{content_type}\n"
            f"host:{self.config.amazon_host}\n"
            f"x-amz-date:{amz_date}\n"
            f"x-amz-target:{self._paapi_target}\n"
        )
        signed_headers = "content-encoding;content-type;host;x-amz-date;x-amz-target"
        payload_hash = hashlib.sha256(body).hexdigest()
        canonical_request = "\n".join(
            [
                "POST",
                self._paapi_path,
                "",
                canonical_headers,
                signed_headers,
                payload_hash,
            ]
        )
        credential_scope = f"{date_stamp}/{self.config.amazon_region}/{self._service}/aws4_request"
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                credential_scope,
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            ]
        )
        signing_key = _signature_key(
            self.config.amazon_secret_key,
            date_stamp,
            self.config.amazon_region,
            self._service,
        )
        signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        authorization = (
            "AWS4-HMAC-SHA256 "
            f"Credential={self.config.amazon_access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        return {
            "Content-Encoding": "amz-1.0",
            "Content-Type": content_type,
            "Host": self.config.amazon_host,
            "X-Amz-Date": amz_date,
            "X-Amz-Target": self._paapi_target,
            "Authorization": authorization,
        }


def _signature_key(secret_key: str, date_stamp: str, region_name: str, service_name: str) -> bytes:
    key_date = hmac.new(("AWS4" + secret_key).encode("utf-8"), date_stamp.encode("utf-8"), hashlib.sha256).digest()
    key_region = hmac.new(key_date, region_name.encode("utf-8"), hashlib.sha256).digest()
    key_service = hmac.new(key_region, service_name.encode("utf-8"), hashlib.sha256).digest()
    return hmac.new(key_service, b"aws4_request", hashlib.sha256).digest()


def _records_from_payload(payload: object) -> list[dict[str, object]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("products", "items", "offers", "data", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                nested = _records_from_payload(value)
                if nested:
                    return nested
    return []


def _read_csv(path: Path) -> list[dict[str, object]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def _deep_value(value: object, path: tuple[str, ...]) -> object:
    current = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _deep_value_any(value: object, path: tuple[str, ...]) -> object:
    current = value
    for key in path:
        if not isinstance(current, dict):
            return None
        if key in current:
            current = current.get(key)
            continue
        lower_key = key[:1].lower() + key[1:]
        upper_key = key[:1].upper() + key[1:]
        current = current.get(lower_key) if lower_key in current else current.get(upper_key)
    return current


def _first(value: object) -> dict[str, object]:
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return value[0]
    return {}


def _as_float(value: object) -> float:
    if value is None:
        return 0.0
    text = re.sub(r"[^0-9,.\-]", "", str(value).strip()).strip(".,")
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


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes", "sim", "prime", "free", "gratis"}


def _creators_token_url(version: str) -> str:
    return {
        "2.1": "https://creatorsapi.auth.us-east-1.amazoncognito.com/oauth2/token",
        "2.2": "https://creatorsapi.auth.eu-south-2.amazoncognito.com/oauth2/token",
        "2.3": "https://creatorsapi.auth.us-west-2.amazoncognito.com/oauth2/token",
        "3.1": "https://api.amazon.com/auth/o2/token",
        "3.2": "https://api.amazon.co.uk/auth/o2/token",
        "3.3": "https://api.amazon.co.jp/auth/o2/token",
    }.get(version, "https://api.amazon.com/auth/o2/token")


def _creators_token_request(token_url: str, version: str, credential_id: str, credential_secret: str) -> Request:
    if version.startswith("2."):
        credentials = base64.b64encode(f"{credential_id}:{credential_secret}".encode("utf-8")).decode("ascii")
        return Request(
            token_url,
            data=urlencode({"grant_type": "client_credentials", "scope": "creatorsapi/default"}).encode("utf-8"),
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "User-Agent": "afiliado-bot/0.1",
            },
            method="POST",
        )
    return Request(
        token_url,
        data=json.dumps(
            {
                "grant_type": "client_credentials",
                "client_id": credential_id,
                "client_secret": credential_secret,
                "scope": "creatorsapi::default",
            },
            separators=(",", ":"),
        ).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "afiliado-bot/0.1",
        },
        method="POST",
    )
