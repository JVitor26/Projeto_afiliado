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
        products = self.storage.list_candidates(
            limit=limit,
            min_score=self.config.min_score_to_publish if min_score is None else min_score,
            unpublished_only=not dry_run,
        )
        sent = 0
        for product in products:
            message = build_offer_message(product, self.config.public_base_url)
            for poster in self.posters:
                results = poster.post(message, product)
                for result in results:
                    status = "sent" if result.success and not dry_run else "preview" if dry_run else "failed"
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

    source_name = {
        "aliexpress": "AliExpress",
        "mercadolivre": "Mercado Livre",
        "shopee": "Shopee",
        "amazon": "Amazon",
        "manual": "Manual",
    }.get(product.source, product.source.title())
    price = _format_money(product.price, product.currency, source_name)
    price_line = _price_line(product, price, source_name)
    lines = [f"<b>{escape(product.title)}</b> | {price_line}"]

    coupon_code = str(product.metadata.get("coupon_code") or "").strip()
    coupon_discount = _as_float(product.metadata.get("coupon_discount"))
    if coupon_code or coupon_discount:
        discount_text = (
            f" de {escape(_format_money(coupon_discount, product.currency, source_name))}"
            if coupon_discount
            else ""
        )
        coupon_suffix = f" Use o cupom <b>{escape(coupon_code)}</b>." if coupon_code else ""
        lines.extend(["", f"✌️ Destaque o cupom{discount_text} na página do produto!{coupon_suffix}"])
    elif product.discount_percent:
        lines.extend(["", f"🔥 Oferta com {product.discount_percent:.0f}% OFF no produto!"])

    if product.free_shipping:
        lines.append("💸 Frete Grátis (Consultar CEP)")

    installment_line = _installment_line(product, source_name)
    if installment_line:
        lines.append(f"✅ {installment_line}")

    search_code = str(product.metadata.get("search_code") or "").strip()
    if search_code:
        lines.append(f"🔎 Código Mercado Livre: <b>{escape(search_code)}</b>")

    if product.rating:
        lines.append(f"⭐ Avaliação: {product.rating:.1f}/5")
    if product.sold_quantity:
        lines.append(f"🛍️ Vendidos: {product.sold_quantity}")

    commission_rate = _as_float(product.metadata.get("commission_rate"))
    if commission_rate:
        lines.append(f"💰 Comissão: {commission_rate * 100:.2f}%")

    lines.extend(["", f"➡️ <b>COMPRE PELO SITE:</b> {escape(link, quote=True)}"])
    return "\n".join(lines)


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
