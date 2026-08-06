from __future__ import annotations

import json
import logging
from html import escape
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from afiliado_bot.config import AppConfig
from afiliado_bot.models import Product
from afiliado_bot.posters.base import Poster
from afiliado_bot.storage import Storage, are_titles_similar

log = logging.getLogger(__name__)


class PublishingService:
    def __init__(self, config: AppConfig, storage: Storage, posters: list[Poster]) -> None:
        self.config = config
        self.storage = storage
        self.posters = posters

    def publish(self, *, limit: int, dry_run: bool = False, min_score: float | None = None) -> int:
        score_floor = self.config.min_score_to_publish if min_score is None else min_score
        products = self.storage.list_candidates(
            limit=limit,
            min_score=score_floor,
            unpublished_only=not dry_run,
        )
        is_repost = False
        if not products and not dry_run and self.config.repost_after_minutes > 0:
            products = self.storage.list_repost_candidates(
                limit=limit,
                min_score=score_floor,
                cooldown_minutes=self.config.repost_after_minutes,
            )
            is_repost = True

        # Deduplicação por similaridade: evita repetir a mesma família de produto
        # (variações de cor/tamanho/modelo) publicada recentemente — vale também
        # para reposts, já que o cooldown por produto não cobre variantes com
        # external_id diferente.
        recent_titles = self.storage.recently_published_titles(hours=12)

        sent = 0
        published_this_run: list[str] = []  # títulos postados nesta execução
        skipped_as_duplicate: list[Product] = []

        for product in products:
            # Evita publicar variantes similares em sequência (ex: mesmo produto, cores diferentes)
            all_recent = recent_titles + published_this_run
            if all_recent and any(are_titles_similar(product.title, t) for t in all_recent):
                log.debug("skip-dedup: similar ja publicado: %s", product.title[:60])
                skipped_as_duplicate.append(product)
                continue

            sent += self._send_product(product, dry_run)
            if not dry_run:
                published_this_run.append(product.title)

        # Repost: se todos os candidatos foram descartados por similaridade, é
        # melhor repetir um produto do que deixar o canal em silêncio.
        if sent == 0 and is_repost and not dry_run and skipped_as_duplicate:
            sent += self._send_product(skipped_as_duplicate[0], dry_run)

        if sent == 0 and not dry_run:
            self._alert_zero_published(len(products))

        return sent

    def _send_product(self, product: Product, dry_run: bool) -> int:
        message = build_offer_message(product, self.config.public_base_url)
        sent = 0
        for poster in self.posters:
            results = poster.post(message, product)
            for result in results:
                status = "sent" if result.success and not dry_run else "preview" if dry_run else "failed"
                if result.success:
                    log.info("[%s] %s", result.channel, status)
                else:
                    log.warning("[%s] %s: %s", result.channel, status, result.response[:120])
                if product.id is not None:
                    self.storage.add_post(
                        product.id,
                        result.channel,
                        status,
                        message,
                        result.response,
                    )
                if result.success:
                    sent += 1
        return sent

    def _alert_zero_published(self, candidates: int) -> None:
        """Envia alerta Telegram quando nenhum produto foi publicado."""
        token = self.config.telegram_bot_token
        chat_ids = self.config.telegram_chat_ids
        if not token or not chat_ids:
            log.warning("Nenhum produto publicado e Telegram nao configurado para alertar.")
            return

        text = (
            "⚠️ <b>Alerta PromoLink</b>\n\n"
            f"Nenhum produto publicado nesta execução.\n"
            f"Candidatos encontrados no banco: {candidates}\n\n"
            "Verifique o banco de dados, os filtros de score e as APIs dos providers."
        )
        for chat_id in chat_ids:
            _send_telegram_text(token, chat_id, text)


def _send_telegram_text(token: str, chat_id: str, text: str) -> None:
    data = urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }).encode("utf-8")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    req = Request(url, data=data)
    try:
        with urlopen(req, timeout=10):
            pass
    except (URLError, OSError) as exc:
        log.warning("Falha ao enviar alerta Telegram: %s", exc)


def build_offer_message(product: Product, public_base_url: str = "") -> str:
    link = product.affiliate_url
    if public_base_url and product.id is not None:
        link = f"{public_base_url}/r/{product.id}"

    source_name = _source_name(product.source)
    price = _format_money(product.price, product.currency, source_name)

    coupon_code = str(product.metadata.get("coupon_code") or "").strip()
    coupon_discount = _as_float(product.metadata.get("coupon_discount"))
    discount_pct = int(product.discount_percent or 0)
    has_original = bool(product.original_price and product.original_price > product.price > 0)
    is_flash = str(product.metadata.get("offer_type") or "").lower() in ("flash", "relâmpago", "deal_of_day")

    bestseller_rank = _as_int(product.metadata.get("bestseller_rank"))
    bestseller_category = str(product.metadata.get("bestseller_category") or "").strip()

    # ── Cabeçalho com urgência ──────────────────────────────
    if is_flash:
        header = "⚡ <b>OFERTA RELÂMPAGO! CORRE!</b>"
    elif coupon_code:
        header = "🎟️ <b>CUPOM EXCLUSIVO DE DESCONTO!</b>"
    elif discount_pct >= 60:
        header = f"🚨 <b>IMPERDÍVEL — {discount_pct}% OFF!</b>"
    elif discount_pct >= 40:
        header = f"🔥 <b>OFERTA QUENTE — {discount_pct}% OFF!</b>"
    elif discount_pct >= 20:
        header = f"💥 <b>DESCONTO DE {discount_pct}% OFF!</b>"
    elif bestseller_rank:
        header = f"🏆 <b>TOP #{bestseller_rank} MAIS VENDIDOS — {source_name.upper()}!</b>"
    else:
        header = f"🛒 <b>OFERTA DO DIA — {source_name.upper()}!</b>"

    lines = [header, ""]

    # ── Produto ─────────────────────────────────────────────
    lines.append(f"📦 {escape(product.title)}")
    lines.append("")

    # ── Preço ───────────────────────────────────────────────
    if has_original:
        original = _format_money(product.original_price, product.currency, source_name)
        saving = product.original_price - product.price
        saving_fmt = _format_money(saving, product.currency, source_name)
        lines.append(f"🏷️ De: <s>{escape(original)}</s>")
        lines.append(f"✅ <b>Por: {escape(price)}</b>{_payment_suffix(product)}")
        lines.append(f"💰 <b>Economia de {escape(saving_fmt)}!</b>")
    else:
        lines.append(f"✅ <b>{escape(price)}</b>{_payment_suffix(product)}")

    # ── Frete ───────────────────────────────────────────────
    if product.free_shipping:
        lines.append("🚚 <b>FRETE GRÁTIS!</b>")

    # ── Parcelas ────────────────────────────────────────────
    installment_line = _installment_line(product, source_name)
    if installment_line:
        lines.append(f"💳 {escape(installment_line)}")

    # ── Cupom ───────────────────────────────────────────────
    if coupon_code or coupon_discount:
        lines.append("")
        if coupon_code:
            lines.append(f"🎟️ <b>CUPOM:</b> <code>{escape(coupon_code)}</code>")
        if coupon_discount:
            cd_fmt = _format_money(coupon_discount, product.currency, source_name)
            lines.append(f"   ↳ Desconto extra de <b>{escape(cd_fmt)}</b> na página!")
        else:
            lines.append("   ↳ Aplique o cupom na página do produto!")

    # ── Código Mercado Livre ─────────────────────────────────
    search_code = str(product.metadata.get("search_code") or "").strip()
    if search_code:
        lines.extend(["", f"🔎 <b>Busque no Mercado Livre:</b> {escape(search_code)}"])

    # ── Avaliação e vendas ──────────────────────────────────
    proof_parts = []
    if bestseller_rank and bestseller_category:
        proof_parts.append(f"🏆 #{bestseller_rank} em {escape(bestseller_category)}")
    if product.rating and product.rating >= 4.0:
        stars = "⭐" * min(5, round(product.rating))
        proof_parts.append(f"{stars} {product.rating:.1f}/5")
    if product.sold_quantity and product.sold_quantity >= 50:
        # No ranking da Amazon esse numero e a quantidade de avaliacoes, nao de vendas.
        label = "avaliações" if bestseller_rank else "vendidos"
        amount = f"{product.sold_quantity:,}".replace(",", ".")
        proof_parts.append(f"🛍️ +{amount} {label}")
    if proof_parts:
        lines.extend(["", " · ".join(proof_parts)])

    # ── CTA ─────────────────────────────────────────────────
    lines.extend([
        "",
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄",
        f"👉 <b>COMPRAR AGORA</b>",
        f"🔗 {escape(link, quote=True)}",
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄",
        "",
        "<i>⚠️ Preços e disponibilidade podem variar. Confira antes de comprar.</i>",
    ])

    return "\n".join(lines)


def _source_name(source: str) -> str:
    return {
        "aliexpress": "AliExpress",
        "mercadolivre": "Mercado Livre",
        "shopee": "Shopee",
        "amazon": "Amazon",
        "manual": "Manual",
    }.get(source, source.title() if source else "Marketplace")


def _price_line(product: Product, price: str, source_name: str) -> str:
    if product.original_price and product.original_price > product.price > 0:
        original = _format_money(product.original_price, product.currency, source_name)
        return f"De <s>{escape(original)}</s> Por <b>{escape(price)}</b>{_payment_suffix(product)}"
    return f"Por <b>{escape(price)}</b>{_payment_suffix(product)}"


def _payment_suffix(product: Product) -> str:
    label = str(product.metadata.get("payment_suffix") or product.metadata.get("payment_method") or "").strip()
    if label:
        return f" ({escape(label)})"
    if product.source == "mercadolivre" and product.price > 0:
        return " (no Pix)"
    return ""


def _installment_line(product: Product, source_name: str) -> str:
    installments = product.metadata.get("installments")
    if not isinstance(installments, dict):
        return ""
    quantity = _as_int(installments.get("quantity"))
    amount = _as_float(installments.get("amount"))
    if not quantity or not amount:
        return ""
    return f"Ou {quantity}x de {_format_money(amount, product.currency, source_name)} no cartão"


def _format_money(value: float, currency: str, source_name: str) -> str:
    if value <= 0:
        return f"conferir na {source_name}"
    if currency.upper() == "BRL":
        text = f"R$ {value:,.2f}"
        return text.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{currency} {value:.2f}"


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
