"""Base compartilhada pelos painéis de afiliado lidos com navegador.

Shopee e AliExpress nao liberaram API para a conta, entao a alternativa e
automatizar o que se faz na mao no painel de cada uma: abrir a oferta e clicar
em "Obter link" / "Get link".

Aqui fica o que os dois tem em comum — modelo de oferta, gravacao no CSV que o
`mine` ja consome e o carregamento opcional do Playwright. Os seletores e o
passo a passo de cada site ficam em seus proprios modulos.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path


class PanelError(RuntimeError):
    pass


@dataclass
class PanelOffer:
    title: str = ""
    price: float = 0.0
    original_price: float | None = None
    commission_rate: float | None = None
    sold_quantity: int | None = None
    rating: float | None = None
    image_url: str = ""
    product_url: str = ""
    affiliate_url: str = ""
    discount_percent: float | None = None
    notes: str = ""


@dataclass
class PanelReport:
    collected: int = 0
    without_link: int = 0
    offers: list[PanelOffer] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def playwright_or_explain():
    """Carrega o Playwright, que e dependencia opcional do projeto."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - depende do ambiente
        raise PanelError(
            "Playwright nao instalado. Rode:\n"
            "  pip install playwright\n"
            "  playwright install chromium"
        ) from exc
    return sync_playwright


def write_manual_csv(
    offers: list[PanelOffer],
    csv_path: Path,
    *,
    source: str,
    append: bool = True,
) -> int:
    """Grava as ofertas no CSV manual que o `mine` ja consome.

    Deduplica pelo link de afiliado: rodar a coleta de novo nao repete produto.
    """
    from afiliado_bot.clients.manual import manual_csv_headers

    headers = manual_csv_headers()
    rows: list[dict[str, str]] = []
    seen: set[str] = set()

    if append and csv_path.exists():
        with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                rows.append(row)
                link = (row.get("affiliate_url") or "").strip()
                if link:
                    seen.add(link)

    added = 0
    for offer in offers:
        if not offer.affiliate_url or offer.affiliate_url in seen:
            continue
        seen.add(offer.affiliate_url)
        rows.append(
            {
                "approved": "yes",
                "source": source,
                "title": offer.title,
                "price": f"{offer.price:.2f}" if offer.price else "",
                "original_price": f"{offer.original_price:.2f}" if offer.original_price else "",
                "currency": "BRL",
                "url": offer.product_url,
                "affiliate_url": offer.affiliate_url,
                "image_url": offer.image_url,
                "category": "",
                "rating": f"{offer.rating:.1f}" if offer.rating else "",
                "sold_quantity": str(offer.sold_quantity) if offer.sold_quantity else "",
                "free_shipping": "",
                "commission_rate": f"{offer.commission_rate:.4f}" if offer.commission_rate else "",
                "keywords": "",
                "notes": offer.notes or f"importado do painel {source}",
            }
        )
        added += 1

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in headers})

    return added


def money(text: str) -> float:
    """Converte 'R$ 1.234,56' ou '133,59' em float."""
    cleaned = re.sub(r"[^\d.,]", "", str(text or "")).strip()
    if not cleaned:
        return 0.0
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def sold_to_int(number: str, unit: str | None = None) -> int | None:
    """'1.000+ sold' -> 1000; '1,000+ sold' -> 1000; '7mil+' -> 7000.

    Quantidade vendida e sempre inteira, entao ponto e virgula sao separadores
    de milhar — nao decimais. O AliExpress usa virgula ("1,000 sold") na mesma
    pagina em que o preco usa virgula como decimal ("R$133,59"), entao tratar os
    dois do mesmo jeito transformaria 1.000 vendas em 1.
    """
    digits = re.sub(r"[^\d]", "", str(number or ""))
    if not digits:
        return None
    value = int(digits)
    if unit and unit.lower() in {"mil", "k"}:
        value *= 1000
    return value
