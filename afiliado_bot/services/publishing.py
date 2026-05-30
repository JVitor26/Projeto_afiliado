from __future__ import annotations

from html import escape

from afiliado_bot.config import AppConfig
from afiliado_bot.models import Product
from afiliado_bot.posters.base import Poster
from afiliado_bot.storage import Storage


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
        if not products and not dry_run and self.config.repost_after_minutes > 0:
            products = self.storage.list_repost_candidates(
                limit=limit,
                min_score=score_floor,
                cooldown_minutes=self.config.repost_after_minutes,
            )

        sent = 0
        for product in products:
            message = build_offer_message(product, self.config.public_base_url)
            for poster in self.posters:
                results = poster.post(message, product)
                for result in results:
                    status = "sent" if result.success and not dry_run else "preview" if dry_run else "failed"
                    print(f"  [{result.channel}] {status}: {result.response[:120] if not result.success else 'ok'}")
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
    if product.rating and product.rating >= 4.0:
        stars = "⭐" * min(5, round(product.rating))
        proof_parts.append(f"{stars} {product.rating:.1f}/5")
    if product.sold_quantity and product.sold_quantity >= 50:
        proof_parts.append(f"🛍️ +{product.sold_quantity:,} vendidos")
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
