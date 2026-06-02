"""Helpers para exportação da loja estática, importação e categorização de produtos."""
from __future__ import annotations

import json
from pathlib import Path

from afiliado_bot.storage import Storage

_DEPARTMENT_GROUPS = [
    (
        "Tecnologia",
        (
            "celular", "smartphone", "iphone", "notebook", "monitor", "ssd",
            "fone", "headset", "bluetooth", "smartwatch", "tablet", "teclado",
            "mouse", "controle", "xbox", "playstation", "gamer", "caixa de som",
        ),
    ),
    (
        "Casa e cozinha",
        (
            "casa", "cozinha", "air fryer", "panela", "liquidificador", "cafeteira",
            "utensilio", "utensílio", "jogo de panelas", "organizador",
            "luminaria", "luminária",
        ),
    ),
    (
        "Eletrodomesticos",
        (
            "geladeira", "micro-ondas", "microondas", "maquina de lavar",
            "máquina de lavar", "aspirador", "ventilador", "climatizador",
            "fritadeira", "britania", "britânia",
        ),
    ),
    ("Cama, mesa e banho", ("cama", "mesa", "banho", "toalha", "jogo de cama", "lencol", "lençol")),
    ("Ferramentas", ("furadeira", "parafusadeira", "ferramenta", "chave", "broca")),
    ("Moda", ("tenis", "tênis", "mochila", "camiseta", "calca", "calça", "relogio", "relógio")),
    ("Beleza", ("beleza", "barbeador", "escova secadora", "secador", "perfume", "maquiagem")),
    ("Pets", ("pet", "cachorro", "gato", "racao", "ração")),
    ("Brinquedos", ("brinquedo", "lego", "boneca", "carrinho")),
    ("Automotivo", ("carro", "moto", "automotivo", "pneu", "bateria")),
]


def display_category_for_product(product: object) -> tuple[str, str]:
    title = str(getattr(product, "title", "") or "")
    raw_category = str(getattr(product, "category", "") or "")
    metadata = getattr(product, "metadata", {}) or {}
    keyword = str(metadata.get("keyword") or metadata.get("keywords") or "").strip()
    is_marketplace_code = raw_category.upper().startswith(("MLB", "MLA", "MLM", "MCO", "MLC", "MLU"))
    readable = raw_category or keyword or "geral"
    if is_marketplace_code and keyword:
        readable = keyword

    department = "Outras ofertas"
    category_text = readable.lower()
    for label, terms in _DEPARTMENT_GROUPS:
        if any(term in category_text for term in terms):
            department = label
            break

    haystack = f"{title} {readable} {raw_category}".lower()
    for label, terms in _DEPARTMENT_GROUPS:
        if department != "Outras ofertas":
            break
        if any(term in haystack for term in terms):
            department = label
            break

    return department, _clean_category_label(readable, title)


def _clean_category_label(value: str, title: str) -> str:
    text = value.strip()
    if not text or text.upper().startswith(("MLB", "MLA", "MLM", "MCO", "MLC", "MLU")):
        text = title
    text = text.replace("_", " ").replace("-", " ")
    text = " ".join(text.split())
    if not text:
        return "Geral"
    return text[:1].upper() + text[1:]


def export_store_products(
    storage: Storage,
    out_path: Path,
    *,
    limit: int,
    keep_existing_if_empty: bool = False,
) -> None:
    products = storage.list_products_for_store(limit=limit, require_image=True)
    payload = []
    for product in products:
        department, category_label = display_category_for_product(product)
        payload.append(
            {
                "id": product.id,
                "source": product.source,
                "externalId": product.external_id,
                "title": product.title,
                "price": product.price,
                "originalPrice": product.original_price,
                "currency": product.currency,
                "affiliateUrl": product.affiliate_url,
                "imageUrl": product.image_url,
                "category": product.category,
                "categoryLabel": category_label,
                "department": department,
                "score": product.score,
                "rating": product.rating,
                "soldQuantity": product.sold_quantity,
                "freeShipping": product.free_shipping,
                "discountPercent": product.discount_percent,
                "commissionRate": product.metadata.get("commission_rate"),
                "offerType": product.metadata.get("offer_type"),
                "periodEndTime": product.metadata.get("period_end_time"),
                "sellerCompletedTransactions": product.metadata.get("seller_completed_transactions"),
                "sellerPowerStatus": product.metadata.get("seller_power_seller_status"),
                "sellerLevel": product.metadata.get("seller_level_id"),
                "officialStoreId": product.metadata.get("official_store_id"),
                "officialStoreName": product.metadata.get("official_store_name"),
            }
        )

    if keep_existing_if_empty and not payload and out_path.exists():
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        "window.LUMINA_PRODUCTS = "
        + json.dumps(payload, ensure_ascii=False, indent=2)
        + ";\n",
        encoding="utf-8",
    )


def generate_stats_js(storage: Storage, out_path: Path) -> None:
    """Gera site/stats.js com métricas do banco para o dashboard estático."""
    data = storage.stats()
    data["clicks_by_source"] = storage.stats_by_source()
    data["clicks_by_category"] = storage.stats_by_category()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        "window.LUMINA_STATS = "
        + json.dumps(data, ensure_ascii=False, indent=2)
        + ";\n",
        encoding="utf-8",
    )


def import_site_products(storage: Storage, products_path: Path, *, limit: int, only_if_empty: bool = False) -> int:
    from afiliado_bot.models import Product

    if only_if_empty and storage.stats()["products"] > 0:
        return 0
    if not products_path.exists():
        return 0

    payload = _load_site_products(products_path)
    imported = 0
    for record in payload[: max(limit, 0)]:
        if not isinstance(record, dict):
            continue
        title = str(record.get("title") or "").strip()
        source = str(record.get("source") or "manual").strip().lower() or "manual"
        external_id = str(record.get("externalId") or record.get("external_id") or "").strip()
        affiliate_url = str(record.get("affiliateUrl") or record.get("affiliate_url") or "").strip()
        image_url = str(record.get("imageUrl") or record.get("image_url") or "").strip()
        price = _site_float(record.get("price"))
        if not title or not external_id or not affiliate_url:
            continue

        metadata = {
            key: record.get(key)
            for key in (
                "categoryLabel", "department", "commissionRate", "offerType",
                "periodEndTime", "sellerCompletedTransactions", "sellerPowerStatus",
                "sellerLevel", "officialStoreId", "officialStoreName",
            )
            if record.get(key) is not None
        }
        product = Product(
            source=source,
            external_id=external_id,
            title=title,
            price=price,
            original_price=_site_optional_float(record.get("originalPrice") or record.get("original_price")),
            currency=str(record.get("currency") or "BRL"),
            permalink=str(record.get("permalink") or affiliate_url),
            affiliate_url=affiliate_url,
            image_url=image_url,
            category=str(record.get("category") or record.get("categoryLabel") or "site"),
            score=_site_float(record.get("score")),
            rating=_site_optional_float(record.get("rating")),
            sold_quantity=_site_optional_int(record.get("soldQuantity") or record.get("sold_quantity")),
            free_shipping=bool(record.get("freeShipping") or record.get("free_shipping")),
            metadata={"raw_source": "site_products", **metadata},
        )
        storage.upsert_product(product)
        imported += 1
    return imported


def _load_site_products(products_path: Path) -> list[object]:
    content = products_path.read_text(encoding="utf-8-sig").strip()
    prefix = "window.LUMINA_PRODUCTS = "
    if content.startswith(prefix):
        content = content[len(prefix):]
    if content.endswith(";"):
        content = content[:-1]
    payload = json.loads(content)
    return payload if isinstance(payload, list) else []


def _site_float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _site_optional_float(value: object) -> float | None:
    parsed = _site_float(value)
    return parsed if parsed > 0 else None


def _site_optional_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
