from __future__ import annotations

import csv
import hashlib
import html
import json
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from afiliado_bot.affiliates import apply_affiliate_template
from afiliado_bot.config import AppConfig
from afiliado_bot.models import Product


class ManualProductClient:
    """Reads manually curated products from a CSV or JSON file."""

    name = "manual"

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    @property
    def enabled(self) -> bool:
        return self.config.manual_products_path.exists()

    def fetch(self, keyword: str, *, limit: int) -> list[Product]:
        products = self.fetch_all(limit=limit * 10 if limit else 0)
        keyword_lower = keyword.lower().strip()
        if not keyword_lower:
            return products[:limit]

        matched = []
        for product in products:
            haystack = " ".join(
                [
                    product.title,
                    product.category,
                    str(product.metadata.get("keywords") or ""),
                    str(product.metadata.get("notes") or ""),
                ]
            ).lower()
            if keyword_lower in haystack:
                matched.append(product)
            if len(matched) >= limit:
                break
        return matched

    def fetch_all(self, *, limit: int = 0) -> list[Product]:
        if not self.enabled:
            return []

        records = _load_records(self.config.manual_products_path)
        products: list[Product] = []
        for index, record in enumerate(records, start=1):
            if not _is_approved(record):
                continue

            title = _first_text(record, "title", "titulo", "name", "nome", "product_title")
            manual_affiliate_url = _first_text(record, "affiliate_url", "link_afiliado")
            permalink = _first_text(
                record,
                "url",
                "link",
                "product_url",
                "permalink",
                default=manual_affiliate_url,
            )
            if not title or not (manual_affiliate_url or permalink):
                continue

            source = _normalize_source(_first_text(record, "source", "marketplace", "loja"), permalink or manual_affiliate_url)
            external_id = _first_text(record, "external_id", "id", "asin", "product_id", "sku")
            if not external_id:
                external_id = _external_id_from_url(source, permalink or manual_affiliate_url) or _stable_id(
                    source,
                    permalink or manual_affiliate_url,
                    title,
                )

            affiliate_url = manual_affiliate_url or _apply_source_template(source, permalink, external_id, self.config)
            category = _first_text(record, "category", "categoria", default="manual")
            commission_rate = _commission_rate(_first_value(record, "commission_rate", "commission", "comissao"))
            products.append(
                Product(
                    source=source,
                    external_id=external_id,
                    title=title,
                    price=_as_float(_first_value(record, "price", "preco", "sale_price", "valor")),
                    original_price=_optional_float(
                        _first_value(record, "original_price", "preco_original", "list_price", "de")
                    ),
                    currency=_first_text(record, "currency", "moeda", default="BRL"),
                    permalink=permalink,
                    affiliate_url=affiliate_url,
                    image_url=_first_text(record, "image_url", "imagem", "image", "foto"),
                    category=category,
                    rating=_optional_float(_first_value(record, "rating", "avaliacao", "stars")),
                    sold_quantity=_optional_int(_first_value(record, "sold_quantity", "vendidos", "sales")),
                    free_shipping=_as_bool(_first_value(record, "free_shipping", "frete_gratis", "prime")),
                    metadata={
                        "keyword": _first_text(record, "keywords", "palavras_chave", default=category),
                        "keywords": _first_text(record, "keywords", "palavras_chave"),
                        "notes": _first_text(record, "notes", "observacoes", "obs"),
                        "raw_source": "manual_feed",
                        "row_number": index,
                        "commission_rate": commission_rate,
                    },
                )
            )
            if limit and len(products) >= limit:
                break
        return products


def manual_csv_headers() -> list[str]:
    return [
        "approved",
        "source",
        "title",
        "price",
        "original_price",
        "currency",
        "url",
        "affiliate_url",
        "image_url",
        "category",
        "rating",
        "sold_quantity",
        "free_shipping",
        "commission_rate",
        "keywords",
        "notes",
    ]


def product_from_promo_text(
    text: str,
    config: AppConfig,
    *,
    category: str = "",
    keywords: str = "",
) -> Product:
    clean_text = _repair_mojibake(text.strip())
    url = _extract_url(clean_text)
    source = _normalize_source("", url)
    title = _extract_title(clean_text) or f"Oferta {_source_display_name(source)}"
    price, original_price, currency = _extract_prices(clean_text)
    coupon_code, coupon_discount, period_start, period_end = _extract_coupon(clean_text)
    search_code = _extract_search_code(clean_text)
    discount_text = _extract_discount_text(clean_text)
    product_category = category or _guess_category(title) or source
    external_id = _external_id_from_url(source, url) or _stable_id(source, url, title)
    affiliate_url = url
    permalink = url
    if url:
        affiliate_url = _apply_source_template(source, url, external_id, config)

    return Product(
        source=source,
        external_id=external_id,
        title=title,
        price=price,
        original_price=original_price,
        currency=currency or "BRL",
        permalink=permalink or affiliate_url,
        affiliate_url=affiliate_url,
        category=product_category,
        metadata={
            "keyword": keywords or product_category,
            "keywords": keywords,
            "raw_source": "promo_text",
            "coupon_code": coupon_code,
            "coupon_discount": coupon_discount,
            "search_code": search_code,
            "period_start": period_start,
            "period_end": period_end,
            "discount_text": discount_text,
            "promo_material": clean_text,
        },
    )


def enrich_product_from_url(product: Product, config: AppConfig, *, timeout: int = 20) -> Product:
    if product.source == "amazon":
        return _enrich_amazon_product(product, timeout=timeout)
    if product.source == "mercadolivre":
        return _enrich_mercadolivre_product(product, config, timeout=timeout)
    if product.source == "aliexpress":
        return _enrich_aliexpress_product(product, timeout=timeout)
    if product.source == "shopee":
        return _enrich_shopee_product(product, timeout=timeout)
    return product


def mercadolivre_public_info_from_text(text: str, config: AppConfig, *, timeout: int = 20) -> dict[str, object]:
    product = product_from_promo_text(text, config)
    if product.source != "mercadolivre":
        return {"source": product.source, "error": "o texto/link nao parece ser do Mercado Livre"}

    try:
        product = _enrich_mercadolivre_product(product, config, timeout=timeout)
    except ProviderLookupError as exc:
        return {
            "source": product.source,
            "item_id": product.external_id,
            "link": product.affiliate_url,
            "error": str(exc),
        }

    seller_id = product.metadata.get("seller_id")
    if not seller_id and product.external_id.startswith("MLB"):
        try:
            item = _fetch_mercadolivre_item(product.external_id, timeout=timeout)
            seller_id = item.get("seller_id")
            if seller_id:
                product.metadata["seller_id"] = seller_id
        except (ProviderLookupError, ValueError):
            pass

    return {
        "source": product.source,
        "item_id": product.external_id,
        "seller_id": seller_id or "",
        "seller_name": product.metadata.get("seller_name") or "",
        "title": product.title,
        "price": product.price,
        "currency": product.currency,
        "permalink": product.permalink,
        "affiliate_url": product.affiliate_url,
        "resolved_url": product.metadata.get("resolved_url") or "",
        "error": product.metadata.get("enrichment_error") or "",
    }


def _load_records(path: Path) -> list[dict[str, object]]:
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            return list(csv.DictReader(file))
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _records_from_payload(payload)


def _repair_mojibake(text: str) -> str:
    if "Ã" not in text and "Â" not in text:
        return text
    try:
        return text.encode("latin-1").decode("utf-8")
    except UnicodeError:
        return text


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


def _is_approved(record: dict[str, object]) -> bool:
    value = _first_value(record, "approved", "aprovado", "status")
    if value in (None, ""):
        return True
    text = str(value).strip().lower()
    return text not in {"0", "false", "no", "nao", "não", "rejeitado", "rejeitada", "skip", "ignorar"}


def _normalize_source(source: str, url: str) -> str:
    value = source.lower().strip().replace(" ", "")
    aliases = {
        "amazonbr": "amazon",
        "amazonia": "amazon",
        "ali": "aliexpress",
        "ali_express": "aliexpress",
        "mercadolivre": "mercadolivre",
        "mercadolibre": "mercadolivre",
        "ml": "mercadolivre",
    }
    if value in {"amazon", "aliexpress", "shopee", "mercadolivre", "manual"}:
        return value
    if value in aliases:
        return aliases[value]

    host = urlparse(url).netloc.lower()
    if "amazon." in host or "amzn.to" in host:
        return "amazon"
    if "aliexpress." in host or "s.click.aliexpress." in host:
        return "aliexpress"
    if "shopee." in host or "shp.ee" in host:
        return "shopee"
    if "mercadolivre." in host or "mercadolibre." in host or host == "meli.la":
        return "mercadolivre"
    return "manual"


def _apply_source_template(source: str, url: str, external_id: str, config: AppConfig) -> str:
    if source == "amazon":
        return apply_affiliate_template(
            config.amazon_affiliate_template,
            url,
            affiliate_id=config.amazon_partner_tag,
            source=source,
            external_id=external_id,
        )
    if source == "aliexpress":
        return apply_affiliate_template(
            config.aliexpress_affiliate_template,
            url,
            affiliate_id=config.aliexpress_tracking_id,
            source=source,
            external_id=external_id,
        )
    if source == "shopee":
        return apply_affiliate_template(
            config.shopee_affiliate_template,
            url,
            affiliate_id=config.shopee_affiliate_id,
            source=source,
            external_id=external_id,
        )
    if source == "mercadolivre":
        return apply_affiliate_template(
            config.mercadolivre_affiliate_template,
            url,
            affiliate_id=config.mercadolivre_affiliate_id,
            source=source,
            external_id=external_id,
        )
    return apply_affiliate_template(
        config.manual_affiliate_template,
        url,
        affiliate_id=config.manual_affiliate_id,
        source=source,
        external_id=external_id,
    )


def _external_id_from_url(source: str, url: str) -> str:
    if source == "amazon":
        match = re.search(r"/(?:dp|gp/product|product)/([A-Z0-9]{10})", url, flags=re.IGNORECASE)
        if match:
            return match.group(1).upper()
        match = re.search(r"[?&](?:asin|ASIN)=([A-Z0-9]{10})", url)
        if match:
            return match.group(1).upper()
    if source == "aliexpress":
        match = re.search(r"/item/(\d+)\.html", url, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    if source == "mercadolivre":
        wid_match = re.search(r"[?&#]wid=(MLB\d+)", url, flags=re.IGNORECASE)
        if wid_match:
            return wid_match.group(1).upper()
        match = re.search(r"(MLB-?\d+)", url, flags=re.IGNORECASE)
        if match:
            return match.group(1).replace("-", "").upper()
    return ""


def _source_display_name(source: str) -> str:
    return {
        "aliexpress": "AliExpress",
        "amazon": "Amazon",
        "mercadolivre": "Mercado Livre",
        "shopee": "Shopee",
    }.get(source, source.title() if source else "Marketplace")


def _stable_id(source: str, url: str, title: str) -> str:
    raw = f"{source}|{url}|{title}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _extract_url(text: str) -> str:
    match = re.search(r"https?://[^\s<>\"]+", text)
    if not match:
        return ""
    return match.group(0).rstrip(").,;]")


def _extract_title(text: str) -> str:
    title_lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        normalized = _strip_line_prefix(line).lower()
        if normalized.startswith("principais recomenda"):
            continue
        if "cole este texto no buscador" in normalized or "acesse o link" in normalized:
            continue
        if _looks_like_price_line(line) or _looks_like_coupon_line(line) or "http://" in line or "https://" in line:
            continue
        title_lines.append(_strip_line_prefix(line))
    return " ".join(title_lines).strip()


def _strip_line_prefix(line: str) -> str:
    return re.sub(r"^[^\wÀ-ÿ]+", "", line, flags=re.UNICODE).strip()


def _looks_like_price_line(line: str) -> bool:
    lowered = line.lower()
    return any(marker in lowered for marker in ("agora preço", "preço atual", "current price", "sale price"))


def _looks_like_coupon_line(line: str) -> bool:
    lowered = line.lower()
    return any(marker in lowered for marker in ("código disponível", "codigo disponivel", "coupon", "cupom"))


def _extract_prices(text: str) -> tuple[float, float | None, str]:
    currency = "BRL"
    current = 0.0
    original: float | None = None

    current_match = re.search(
        r"(?:agora preço|preço atual|current price|sale price)\s*:\s*([A-Z]{3})?\s*([0-9][0-9.,]*)",
        text,
        flags=re.IGNORECASE,
    )
    if current_match:
        currency = current_match.group(1) or currency
        current = _as_float(current_match.group(2))

    original_match = re.search(
        r"(?:preço original|preco original|original price)\s*:\s*([A-Z]{3})?\s*([0-9][0-9.,]*)",
        text,
        flags=re.IGNORECASE,
    )
    if original_match:
        currency = original_match.group(1) or currency
        original = _optional_float(original_match.group(2))

    return current, original, currency


def _extract_coupon(text: str) -> tuple[str, float | None, str, str]:
    coupon_code = ""
    coupon_discount: float | None = None
    period_start = ""
    period_end = ""

    code_match = re.search(
        r"(?:código disponível|codigo disponivel|cupom|coupon)\s*:\s*([^,\n]+)",
        text,
        flags=re.IGNORECASE,
    )
    if code_match:
        coupon_code = code_match.group(1).strip()

    discount_match = re.search(
        r"(?:código disponível|codigo disponivel|cupom|coupon).*?,\s*[A-Z]{3}\s*([0-9][0-9.,]*)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if discount_match:
        coupon_discount = _optional_float(discount_match.group(1))

    period_match = re.search(
        r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s*~\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})",
        text,
    )
    if period_match:
        period_start = period_match.group(1)
        period_end = period_match.group(2)

    return coupon_code, coupon_discount, period_start, period_end


def _extract_search_code(text: str) -> str:
    match = re.search(
        r"buscador\s+do\s+mercado\s+livre\s*:\s*([A-Z0-9][A-Z0-9-]+)",
        text,
        flags=re.IGNORECASE,
    )
    return match.group(1).upper() if match else ""


def _extract_discount_text(text: str) -> str:
    match = re.search(r"([0-9]+(?:[.,][0-9]+)?)\s*%\s*(?:desligado|off|desconto)", text, flags=re.IGNORECASE)
    return match.group(0) if match else ""


def _guess_category(title: str) -> str:
    lowered = title.lower()
    category_terms = {
        "microfone": ("microfone", "microphone", "mic "),
        "fone bluetooth": ("fone", "earphone", "headphone", "bluetooth"),
        "smartwatch": ("smartwatch", "relógio inteligente", "relogio inteligente"),
        "celular": ("celular", "smartphone", "iphone", "android"),
        "notebook": ("notebook", "laptop"),
        "monitor": ("monitor",),
        "ssd": ("ssd",),
        "air fryer": ("air fryer", "fritadeira"),
        "mochila": ("mochila", "backpack"),
        "tenis": ("tenis", "tênis", "sneaker"),
    }
    for category, terms in category_terms.items():
        if any(term in lowered for term in terms):
            return category
    return ""


def _enrich_mercadolivre_product(product: Product, config: AppConfig, *, timeout: int) -> Product:
    resolved_url, body = _resolve_url(product.affiliate_url or product.permalink, timeout=timeout)
    _apply_mercadolivre_html_metadata(product, body)
    if _has_product_details(product):
        if resolved_url:
            product.metadata["resolved_url"] = resolved_url
        return product

    item_id = _external_id_from_url("mercadolivre", resolved_url) or _extract_mercadolivre_id(body)
    if not item_id:
        product.metadata["enrichment_error"] = "nao foi possivel identificar o item do Mercado Livre"
        if resolved_url:
            product.permalink = resolved_url
        return product

    product.external_id = item_id
    if resolved_url:
        product.permalink = resolved_url

    try:
        item = _fetch_mercadolivre_item(item_id, timeout=timeout)
    except (ProviderLookupError, ValueError) as exc:
        product.metadata["enrichment_error"] = str(exc)
        return product

    product.title = str(item.get("title") or product.title)
    product.price = _as_float(item.get("price")) or product.price
    original_price = _optional_float(item.get("original_price") or item.get("base_price"))
    if original_price and original_price > product.price:
        product.original_price = original_price
    product.currency = str(item.get("currency_id") or product.currency or "BRL")
    product.permalink = str(item.get("permalink") or product.permalink)
    product.image_url = _mercadolivre_image(item) or product.image_url
    product.category = str(item.get("category_id") or product.category or "mercadolivre")
    if item.get("seller_id"):
        product.metadata["seller_id"] = item.get("seller_id")
    product.sold_quantity = _optional_int(item.get("sold_quantity")) or product.sold_quantity
    product.free_shipping = bool((item.get("shipping") or {}).get("free_shipping")) or product.free_shipping
    product.metadata["raw_source"] = "promo_text_mercadolivre"
    product.metadata["resolved_url"] = resolved_url
    return product


def _enrich_amazon_product(product: Product, *, timeout: int) -> Product:
    resolved_url, body = _resolve_url(product.affiliate_url or product.permalink, timeout=timeout)
    if resolved_url:
        product.permalink = resolved_url

    asin = _external_id_from_url("amazon", resolved_url) or _extract_amazon_asin(body)
    if asin:
        product.external_id = asin

    _apply_amazon_html_metadata(product, body)
    if resolved_url:
        product.metadata["resolved_url"] = resolved_url
    product.metadata["raw_source"] = "promo_text_amazon"
    return product


def _enrich_shopee_product(product: Product, *, timeout: int) -> Product:
    """Extrai dados de produto Shopee via OG tags e padrões no HTML."""
    try:
        resolved_url, body = _resolve_url(product.affiliate_url or product.permalink, timeout=timeout)
        if resolved_url:
            product.permalink = resolved_url
            product.metadata["resolved_url"] = resolved_url

        # Título via OG (mais confiável para Shopee)
        og_title = _meta_content(body, "og:title")
        if og_title:
            clean = re.sub(r"\s*[-|]\s*Shopee.*$", "", og_title, flags=re.IGNORECASE).strip()
            if clean and len(clean) > 8:
                product.title = clean

        # Imagem via OG
        og_image = _meta_content(body, "og:image")
        if og_image and not product.image_url:
            product.image_url = og_image

        # Preço: OG tag primeiro, depois padrões no JS embutido
        if product.price <= 0:
            og_price_str = _meta_content(body, "og:price:amount") or _meta_content(body, "product:price:amount")
            if og_price_str:
                product.price = _as_float(og_price_str)

        if product.price <= 0:
            for pat in [
                # Shopee usa centavos * 100000 em alguns endpoints
                r'"price"\s*:\s*(\d{5,})',
                r'"min_price"\s*:\s*(\d{5,})',
                r'"discounted_price"\s*:\s*(\d{5,})',
            ]:
                m = re.search(pat, body)
                if m:
                    raw = int(m.group(1))
                    product.price = round(raw / 100000, 2)
                    break

        # Preço original / desconto
        for pat in [
            r'"price_before_discount"\s*:\s*(\d{5,})',
            r'"original_price"\s*:\s*(\d{5,})',
        ]:
            m = re.search(pat, body)
            if m:
                raw = int(m.group(1))
                original = round(raw / 100000, 2)
                if original > product.price > 0:
                    product.original_price = original
                break

        # Frete grátis
        if "frete grátis" in body.lower() or "free shipping" in body.lower():
            product.free_shipping = True

        # Cupom Shopee
        coupon_m = re.search(r'"coupon_code"\s*:\s*"([A-Z0-9]{4,20})"', body, re.IGNORECASE)
        if coupon_m and not product.metadata.get("coupon_code"):
            product.metadata["coupon_code"] = coupon_m.group(1).upper()

        # External ID (shop_id.item_id)
        m = re.search(r"/i\.(\d+)\.(\d+)", resolved_url or product.permalink)
        if m:
            product.external_id = f"{m.group(1)}.{m.group(2)}"

        if not product.category or product.category == "shopee":
            product.category = _guess_category(product.title) or "shopee"

        product.metadata["raw_source"] = "promo_text_shopee"

    except Exception as exc:
        product.metadata["enrichment_error"] = str(exc)

    return product


def _enrich_aliexpress_product(product: Product, *, timeout: int) -> Product:
    try:
        resolved_url, body = _resolve_url(product.affiliate_url or product.permalink, timeout=timeout)
        if resolved_url:
            product.permalink = resolved_url
            product.metadata["resolved_url"] = resolved_url

        # Tenta extrair titulo do HTML
        title_match = re.search(r'<h1[^>]*>([^<]+)</h1>', body, re.IGNORECASE)
        if title_match:
            extracted_title = title_match.group(1).strip()
            if extracted_title and not product.title.startswith("Oferta "):
                product.title = extracted_title[:200]

        # Tenta extrair preco do JSON/script
        price_match = re.search(r'"(?:price|priceDisplay|salePrice)"[^:]*:\s*([0-9.]+)', body)
        if price_match and product.price <= 0:
            try:
                product.price = float(price_match.group(1))
            except (ValueError, IndexError):
                pass

        product.metadata["raw_source"] = "promo_text_aliexpress"
    except Exception:
        product.metadata["raw_source"] = "promo_text_aliexpress"

    return product


def _has_product_details(product: Product) -> bool:
    return product.price > 0 and not product.title.startswith("Oferta ")


def _resolve_url(url: str, *, timeout: int) -> tuple[str, str]:
    if not url:
        return "", ""
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) afiliado-bot/0.1",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read(700_000).decode("utf-8", errors="replace")
            return response.geturl(), body
    except HTTPError as exc:
        body = exc.read(200_000).decode("utf-8", errors="replace")
        return exc.geturl() or url, body
    except URLError as exc:
        raise ProviderLookupError(f"erro ao abrir link: {exc.reason}") from exc


def _fetch_mercadolivre_item(item_id: str, *, timeout: int) -> dict[str, object]:
    attributes = ",".join(
        [
            "id",
            "title",
            "price",
            "original_price",
            "base_price",
            "currency_id",
            "permalink",
            "pictures",
            "secure_thumbnail",
            "thumbnail",
            "category_id",
            "seller_id",
            "sold_quantity",
            "shipping",
        ]
    )
    multiget_url = f"https://api.mercadolibre.com/items?ids={item_id}&attributes={attributes}"
    try:
        payload = _fetch_json(multiget_url, timeout=timeout)
        if isinstance(payload, list) and payload:
            first = payload[0]
            if isinstance(first, dict):
                body = first.get("body")
                if int(first.get("code") or 0) == 200 and isinstance(body, dict):
                    return body
    except ProviderLookupError:
        pass

    payload = _fetch_json(f"https://api.mercadolibre.com/items/{item_id}", timeout=timeout)
    if not isinstance(payload, dict):
        raise ValueError("resposta invalida do Mercado Livre")
    return payload


def _fetch_json(url: str, *, timeout: int) -> object:
    request = Request(url, headers={"User-Agent": "afiliado-bot/0.1", "Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ProviderLookupError(f"Mercado Livre HTTP {exc.code}: {body[:200]}") from exc
    except URLError as exc:
        raise ProviderLookupError(f"Mercado Livre connection error: {exc.reason}") from exc
    return payload


def _extract_mercadolivre_id(text: str) -> str:
    if not text:
        return ""
    decoded = html.unescape(text)
    patterns = (
        r"[?&#]wid=(MLB\d+)",
        r"\b(MLB-?\d{6,})\b",
        r'"item_id"\s*:\s*"(MLB\d+)"',
        r'"itemId"\s*:\s*"(MLB\d+)"',
        r'"id"\s*:\s*"(MLB\d+)"',
    )
    for pattern in patterns:
        match = re.search(pattern, decoded, flags=re.IGNORECASE)
        if match:
            return match.group(1).replace("-", "").upper()
    return ""


def _apply_mercadolivre_html_metadata(product: Product, body: str) -> None:
    if not body:
        return
    decoded = html.unescape(body)
    title_match = re.search(
        r'<a\s+href="([^"]+)"[^>]*class="poly-component__title"[^>]*>(.*?)</a>',
        decoded,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not title_match:
        title_match = re.search(r'<title>(.*?)</title>', decoded, flags=re.IGNORECASE | re.DOTALL)
        if title_match and product.title.startswith("Oferta "):
            product.title = _strip_tags(title_match.group(1)).replace(" | MercadoLivre", "").strip()
        return

    href = title_match.group(1).strip()
    title = _strip_tags(title_match.group(2)).strip()
    if title:
        product.title = title
    if href:
        product.permalink = href
        product.external_id = _external_id_from_url("mercadolivre", href) or product.external_id

    window_start = max(0, title_match.start() - 2500)
    window_end = min(len(decoded), title_match.end() + 6500)
    card = decoded[window_start:window_end]
    image_match = re.search(r'<img[^>]+class="poly-component__picture"[^>]+src="([^"]+)"', card, flags=re.IGNORECASE)
    if image_match:
        product.image_url = image_match.group(1)

    current_price = _money_from_aria(card, "Agora")
    previous_price = _money_from_aria(card, "Antes")
    if current_price > 0:
        product.price = current_price
    if previous_price and previous_price > product.price:
        product.original_price = previous_price
    if "Frete grátis" in card or "Frete gratis" in card:
        product.free_shipping = True
    seller_match = re.search(
        r'<span[^>]+class="poly-component__seller"[^>]*>(.*?)</span>',
        card,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if seller_match:
        seller_name = _strip_tags(seller_match.group(1)).strip()
        seller_name = re.sub(r"^Por\s+", "", seller_name, flags=re.IGNORECASE).strip()
        if seller_name:
            product.metadata["seller_name"] = seller_name
    if not product.category or product.category == "mercadolivre":
        product.category = _guess_category(product.title) or "mercadolivre"
    discount_match = re.search(r"(\d+%\s*OFF)", card, flags=re.IGNORECASE)
    if discount_match:
        product.metadata["discount_text"] = discount_match.group(1)

    # Cupons e promoções do ML (extraídos do HTML da página)
    if not product.metadata.get("coupon_code"):
        for coupon_pat in [
            r'(?:cupom|coupon|c[oó]digo(?:\s+de\s+desconto)?)\s*[:\-]?\s*([A-Z0-9]{4,20})',
            r'"coupon_code"\s*:\s*"([A-Z0-9]{4,20})"',
            r'data-coupon(?:-code)?=["\']([A-Z0-9]{4,20})["\']',
        ]:
            cm = re.search(coupon_pat, decoded, flags=re.IGNORECASE)
            if cm:
                code = cm.group(1).strip().upper()
                if len(code) >= 4 and not code.startswith("HTTP"):
                    product.metadata["coupon_code"] = code
                    break

    # Valor de cupom/desconto extra em R$
    if not product.metadata.get("coupon_discount"):
        for val_pat in [
            r'desconto\s+(?:extra\s+)?(?:de\s+)?R\$\s*([\d.,]+)',
            r'economize\s+(?:mais\s+)?R\$\s*([\d.,]+)',
            r'"coupon_amount"\s*:\s*([\d.]+)',
        ]:
            vm = re.search(val_pat, decoded, flags=re.IGNORECASE)
            if vm:
                cd = _as_float(vm.group(1))
                if cd > 0:
                    product.metadata["coupon_discount"] = cd
                    break


def _strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value).strip()


def _extract_amazon_asin(text: str) -> str:
    if not text:
        return ""
    patterns = (
        r'"asin"\s*:\s*"([A-Z0-9]{10})"',
        r'"ASIN"\s*:\s*"([A-Z0-9]{10})"',
        r'data-asin="([A-Z0-9]{10})"',
        r'/dp/([A-Z0-9]{10})',
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).upper()
    return ""


def _apply_amazon_html_metadata(product: Product, body: str) -> None:
    if not body:
        return
    decoded = html.unescape(body)

    title = _meta_content(decoded, "og:title")
    if not title:
        title_match = re.search(
            r'<span[^>]+id=["\']productTitle["\'][^>]*>(.*?)</span>',
            decoded,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if title_match:
            title = _strip_tags(title_match.group(1))
    if not title:
        title_match = re.search(r"<title>(.*?)</title>", decoded, flags=re.IGNORECASE | re.DOTALL)
        if title_match:
            title = _strip_tags(title_match.group(1)).replace("Amazon.com.br:", "").strip()
    if title and not _is_amazon_block_title(title):
        product.title = _clean_amazon_title(title)

    image_url = _meta_content(decoded, "og:image")
    if not image_url:
        image_url = _html_attr(decoded, r'id=["\']landingImage["\'][^>]+(?:data-old-hires|src)=["\']([^"\']+)["\']')
    if image_url:
        product.image_url = image_url

    price = _amazon_price(decoded)
    if price > 0:
        product.price = price
    original_price = _amazon_original_price(decoded)
    if original_price and original_price > product.price:
        product.original_price = original_price
    if not product.category or product.category == "amazon":
        product.category = _guess_category(product.title) or "amazon"


def _meta_content(text: str, name: str) -> str:
    for match in re.finditer(r"<meta\b[^>]*>", text, flags=re.IGNORECASE | re.DOTALL):
        tag = match.group(0)
        property_value = _html_attr(tag, r'(?:property|name)=["\']([^"\']+)["\']')
        if property_value.lower() != name.lower():
            continue
        return _html_attr(tag, r'content=["\']([^"\']+)["\']')
    return ""


def _clean_amazon_title(title: str) -> str:
    clean = re.sub(r"\s+", " ", title).strip()
    clean = re.sub(r"^Amazon\.com\.br\s*:\s*", "", clean, flags=re.IGNORECASE).strip()
    clean = re.sub(r"\s*:\s*Amazon\.com\.br\s*:?.*$", "", clean, flags=re.IGNORECASE).strip()
    clean = re.sub(r"\s*\|\s*Amazon\.com\.br\s*$", "", clean, flags=re.IGNORECASE).strip()
    return clean


def _is_amazon_block_title(title: str) -> bool:
    lowered = title.lower()
    return any(marker in lowered for marker in ("robot check", "amazon captcha", "digite os caracteres"))


def _html_attr(text: str, pattern: str) -> str:
    match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else ""


def _amazon_price(text: str) -> float:
    for pattern in (
        r'"priceAmount"\s*:\s*([0-9]+(?:\.[0-9]+)?)',
        r'"price"\s*:\s*"?(?:R\$)?\s*([0-9]+(?:[.,][0-9]+)?)',
        r'<meta[^>]+property=["\']product:price:amount["\'][^>]+content=["\']([0-9]+(?:[.,][0-9]+)?)["\']',
        r'id=["\']priceblock_(?:ourprice|dealprice|saleprice)["\'][^>]*>\s*(?:R\$)?\s*([0-9.]+,[0-9]{2}|[0-9]+(?:\.[0-9]{2})?)',
    ):
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return _as_float(match.group(1))

    price_match = re.search(
        r'class=["\'][^"\']*a-price-whole[^"\']*["\'][^>]*>\s*([0-9.]+)\s*<.*?class=["\'][^"\']*a-price-fraction[^"\']*["\'][^>]*>\s*([0-9]{2})',
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if price_match:
        return _as_float(f"{price_match.group(1)},{price_match.group(2)}")
    return 0.0


def _amazon_original_price(text: str) -> float | None:
    match = re.search(
        r'class=["\'][^"\']*a-price\s+a-text-price[^"\']*["\'].*?class=["\'][^"\']*a-offscreen[^"\']*["\'][^>]*>\s*(?:R\$)?\s*([0-9.]+,[0-9]{2}|[0-9]+(?:\.[0-9]{2})?)',
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match:
        return _optional_float(match.group(1))
    return None


def _money_from_aria(text: str, label: str) -> float:
    match = re.search(
        rf'aria-label="{label}:\s*([0-9.]+)\s+rea(?:l|is)(?:\s+com\s+([0-9]+)\s+centavos?)?',
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return 0.0
    reais = _as_float(match.group(1))
    cents = int(match.group(2) or 0)
    return round(reais + cents / 100, 2)


def _mercadolivre_image(item: dict[str, object]) -> str:
    pictures = item.get("pictures")
    if isinstance(pictures, list) and pictures and isinstance(pictures[0], dict):
        return str(pictures[0].get("secure_url") or pictures[0].get("url") or "")
    return str(item.get("secure_thumbnail") or item.get("thumbnail") or "")


class ProviderLookupError(RuntimeError):
    pass


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
    text = text.strip(".,")
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


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "sim", "gratis", "free", "prime"}
