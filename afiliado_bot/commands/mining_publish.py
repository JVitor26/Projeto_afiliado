"""Helpers de mineração e publicação manual de produtos."""
from __future__ import annotations

import dataclasses
from pathlib import Path

from afiliado_bot.clients.base import ProductProvider
from afiliado_bot.config import AppConfig
from afiliado_bot.scoring import ProductRanker
from afiliado_bot.services.mining import MiningService
from afiliado_bot.services.publishing import PublishingService, build_offer_message
from afiliado_bot.storage import Storage


def run_provider_auto(
    config: AppConfig,
    storage: Storage,
    *,
    provider: ProductProvider,
    keywords: list[str],
    limit_per_keyword: int,
    publish_limit: int,
    min_score: float,
    site_out: Path,
    site_limit: int,
    dry_run: bool,
) -> dict[str, object]:
    from afiliado_bot.commands.store import export_store_products
    from afiliado_bot.cli import _build_posters  # noqa: PLC0415

    providers = [provider]
    ranker = ProductRanker(config, storage.category_boosts())
    mining = MiningService(providers, storage, ranker)
    mining_report = mining.mine(keywords, limit_per_keyword=limit_per_keyword)

    if not site_out.is_absolute():
        from afiliado_bot.config import BASE_DIR
        site_out = BASE_DIR / site_out
    export_store_products(storage, site_out, limit=site_limit)

    posters = _build_posters(config, force_dry_run=dry_run)
    publishing = PublishingService(config, storage, posters)
    sent = publishing.publish(limit=publish_limit, dry_run=dry_run, min_score=min_score)

    return {
        "imported": mining_report.imported,
        "skipped": mining_report.skipped,
        "errors": mining_report.errors,
        "site_out": str(site_out),
        "sent": sent,
    }


def add_promo_product(
    config: AppConfig,
    storage: Storage,
    promo_text: str,
    *,
    category: str,
    keywords: str,
    min_score: float,
    dry_run: bool,
    enrich: bool = True,
    require_details: bool = False,
) -> dict[str, object]:
    from afiliado_bot.clients.manual import enrich_product_from_url, product_from_promo_text

    product = product_from_promo_text(promo_text, config, category=category, keywords=keywords)
    if enrich:
        try:
            product = enrich_product_from_url(product, config)
        except RuntimeError as exc:
            product.metadata["enrichment_error"] = str(exc)

    ranker_config = config
    if not require_details and not product.image_url.strip():
        ranker_config = dataclasses.replace(config, require_product_image=False)

    ranker = ProductRanker(ranker_config, storage.category_boosts())
    reason = ranker.reject_reason(product)
    if not reason and require_details and _missing_required_details(product):
        reason = "nao consegui montar titulo e preco pelo link; cole o material completo ou verifique o link"
    status = "rejeitado"
    if reason:
        product.score = 0.0
    else:
        product.score = ranker.score(product)
        if product.score >= min_score:
            status = "aprovado_dry_run" if dry_run else "importado"
            if not dry_run:
                product.id = storage.upsert_product(product)
        else:
            status = "baixo_score"
            reason = f"score abaixo do minimo ({product.score:.2f} < {min_score:.2f})"

    return {
        "status": status,
        "reason": reason or "",
        "product": product,
        "message": build_offer_message(product, config.public_base_url),
    }


def publish_single_product(config: AppConfig, storage: Storage, product: object, *, dry_run: bool) -> int:
    from afiliado_bot.cli import _build_posters  # noqa: PLC0415

    posters = _build_posters(config, force_dry_run=dry_run)
    message = build_offer_message(product, config.public_base_url)  # type: ignore[arg-type]
    sent = 0
    for poster in posters:
        results = poster.post(message, product)
        for result in results:
            status = "sent" if result.success and not dry_run else "preview" if dry_run else "failed"
            if getattr(product, "id", None) is not None:
                storage.add_post(product.id, result.channel, status, message, result.response)
            if result.success:
                sent += 1
    return sent


def _missing_required_details(product: object) -> bool:
    title = getattr(product, "title", "")
    price = float(getattr(product, "price", 0) or 0)
    source = getattr(product, "source", "")
    if title.startswith("Oferta "):
        return True
    if source == "amazon":
        return False
    return price <= 0
