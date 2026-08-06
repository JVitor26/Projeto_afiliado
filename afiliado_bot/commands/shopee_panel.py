"""Le o painel de afiliados da Shopee com um navegador de verdade.

Usado quando a Affiliate Open API nao foi liberada para a conta (erro 10035).
Automatiza exatamente o que se faz na mao em affiliate.shopee.com.br:
abrir "Oferta de produto", ler os cards e clicar em "Obter link" para pegar o
``s.shopee.com.br/...`` de cada produto.

Depende do Playwright, que e opcional de proposito — o resto do bot roda so com
a biblioteca padrao:

    pip install playwright
    playwright install chromium

Fluxo:
    1. ``shopee-panel-login`` abre o navegador para voce entrar na conta uma vez
       e guarda a sessao em ``data/shopee_session.json``.
    2. ``shopee-panel-import`` reusa essa sessao, coleta as ofertas e grava em
       ``data/manual_products.csv``, que o ``mine`` ja consome.

A sessao e credencial: fica fora do git (.gitignore) e nao deve ser commitada.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from .panel_common import (
    PanelError,
    PanelOffer,
    PanelReport,
    money as _money,
    playwright_or_explain,
    sold_to_int as _sales_to_int,
)
from .panel_common import write_manual_csv as _write_manual_csv

log = logging.getLogger(__name__)

PANEL_URL = "https://affiliate.shopee.com.br/offer/product_offer"
LOGIN_URL = "https://affiliate.shopee.com.br/"

# Seletores conferidos no DevTools do painel. Se a Shopee mudar o layout, a
# coleta para e o comando avisa qual seletor falhou — e melhor falhar visivel
# do que gravar produto pela metade.
SEL_CARD = ".product-offer-item"
SEL_NAME = ".ItemCard__name"
SEL_PRICE = ".ItemCard__price"
SEL_COMMISSION = ".commRate"
SEL_IMAGE = ".ItemCard__imageSection img"
SEL_PRODUCT_LINK = 'a[href*="/offer/product_offer/"]'
SEL_GETLINK_BTN = "button.AffiliateItemCard__getlinkBtn"
SEL_MODAL = ".get-link-modal"
SEL_MODAL_LINK = ".get-link-modal .link-area"
SEL_MODAL_CLOSE = ".get-link-modal .ant-modal-close"

_SHORT_LINK = re.compile(r"https://s\.shopee\.com\.br/[A-Za-z0-9]+")
_MONEY = re.compile(r"R\$\s*([\d.,]+)")
_PERCENT = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
_SALES = re.compile(r"([\d.,]+)\s*(mil|k)?\+?\s*vendas", re.IGNORECASE)


def save_session(session_path: Path, *, timeout_seconds: int = 300) -> None:
    """Abre o navegador para login manual e guarda os cookies da sessao."""
    sync_playwright = playwright_or_explain()
    session_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(locale="pt-BR")
        page = context.new_page()
        page.goto(LOGIN_URL)

        print("Entre na sua conta Shopee na janela que abriu.")
        print("Quando o painel de afiliados carregar, volte aqui — o login e detectado sozinho.")

        try:
            # Espera o painel logado: a lista de ofertas so existe apos o login
            page.goto(PANEL_URL, wait_until="domcontentloaded")
            page.wait_for_selector(SEL_CARD, timeout=timeout_seconds * 1000)
        except Exception as exc:  # noqa: BLE001 - qualquer falha aqui e "nao logou"
            browser.close()
            raise PanelError(f"Nao consegui confirmar o login em {timeout_seconds}s: {exc}") from exc

        context.storage_state(path=str(session_path))
        browser.close()

    print(f"Sessao salva em {session_path}")
    print("Esse arquivo e credencial: nao commite e nao compartilhe.")


def collect_offers(
    session_path: Path,
    *,
    limit: int = 20,
    headless: bool = True,
    delay_ms: int = 900,
) -> PanelReport:
    """Coleta ofertas do painel, pegando o link de afiliado de cada produto."""
    if not session_path.exists():
        raise PanelError(
            f"Sessao nao encontrada em {session_path}.\n"
            "Rode primeiro: python -m afiliado_bot shopee-panel-login"
        )

    sync_playwright = playwright_or_explain()
    report = PanelReport()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(storage_state=str(session_path), locale="pt-BR")
        page = context.new_page()
        page.goto(PANEL_URL, wait_until="domcontentloaded")

        try:
            page.wait_for_selector(SEL_CARD, timeout=30000)
        except Exception as exc:  # noqa: BLE001
            browser.close()
            raise PanelError(
                "A lista de ofertas nao carregou. A sessao pode ter expirado — "
                "rode 'shopee-panel-login' de novo.\n"
                f"Detalhe: {exc}"
            ) from exc

        cards = page.query_selector_all(SEL_CARD)
        log.info("cards encontrados na pagina: %d", len(cards))

        for index, card in enumerate(cards):
            if report.collected >= limit:
                break
            try:
                offer = _read_card(card)
            except Exception as exc:  # noqa: BLE001 - um card ruim nao para a coleta
                report.errors.append(f"card {index + 1}: {exc}")
                continue

            if not offer.title:
                report.errors.append(f"card {index + 1}: sem titulo ({SEL_NAME} nao casou)")
                continue

            link = _get_affiliate_link(page, card, delay_ms=delay_ms)
            if not link:
                report.without_link += 1
                report.errors.append(f"{offer.title[:40]}: nao consegui pegar o link de afiliado")
                continue

            offer.affiliate_url = link
            report.offers.append(offer)
            report.collected += 1
            log.info("[%d/%d] %s", report.collected, limit, offer.title[:56])

        browser.close()

    return report


def _read_card(card) -> PanelOffer:
    offer = PanelOffer()

    name_el = card.query_selector(SEL_NAME)
    offer.title = (name_el.inner_text().strip() if name_el else "")

    price_el = card.query_selector(SEL_PRICE)
    if price_el:
        prices = _MONEY.findall(price_el.inner_text())
        if prices:
            offer.price = _money(prices[0])
            # Quando ha dois valores, o segundo costuma ser o preco "de"
            if len(prices) > 1:
                candidate = _money(prices[1])
                if candidate > offer.price:
                    offer.original_price = candidate

    comm_el = card.query_selector(SEL_COMMISSION)
    if comm_el:
        match = _PERCENT.search(comm_el.inner_text())
        if match:
            # Guardado como fracao (6% -> 0.06), igual ao resto do sistema
            offer.commission_rate = round(float(match.group(1).replace(",", ".")) / 100, 4)

    img_el = card.query_selector(SEL_IMAGE)
    if img_el:
        offer.image_url = img_el.get_attribute("src") or ""

    link_el = card.query_selector(SEL_PRODUCT_LINK)
    if link_el:
        href = link_el.get_attribute("href") or ""
        if href.startswith("/"):
            href = "https://affiliate.shopee.com.br" + href
        offer.product_url = href

    text = card.inner_text()
    sales = _SALES.search(text)
    if sales:
        offer.sold_quantity = _sales_to_int(sales.group(1), sales.group(2))
    discount = _PERCENT.search(text)
    if discount and "OFF" in text.upper():
        offer.discount_percent = float(discount.group(1).replace(",", "."))

    return offer


def _get_affiliate_link(page, card, *, delay_ms: int) -> str:
    """Clica em "Obter link" e le o s.shopee.com.br do modal."""
    button = card.query_selector(SEL_GETLINK_BTN)
    if not button:
        return ""

    try:
        button.click()
        page.wait_for_selector(SEL_MODAL, timeout=10000)
        page.wait_for_timeout(delay_ms)

        link = ""
        area = page.query_selector(SEL_MODAL_LINK)
        if area:
            # O link aparece ora como texto, ora dentro de um input
            match = _SHORT_LINK.search(area.inner_text() or "")
            if match:
                link = match.group(0)
            if not link:
                field_el = area.query_selector("input, textarea")
                if field_el:
                    value = field_el.input_value() or field_el.get_attribute("value") or ""
                    found = _SHORT_LINK.search(value)
                    link = found.group(0) if found else ""

        if not link:
            modal = page.query_selector(SEL_MODAL)
            if modal:
                found = _SHORT_LINK.search(modal.inner_text() or "")
                link = found.group(0) if found else ""

        return link
    except Exception as exc:  # noqa: BLE001
        log.debug("falha ao pegar link: %s", exc)
        return ""
    finally:
        close = page.query_selector(SEL_MODAL_CLOSE)
        if close:
            try:
                close.click()
                page.wait_for_timeout(250)
            except Exception:  # noqa: BLE001 - modal ja fechado
                pass


def write_manual_csv(offers: list[PanelOffer], csv_path: Path, *, append: bool = True) -> int:
    """Grava as ofertas coletadas no CSV manual, marcadas como Shopee."""
    return _write_manual_csv(offers, csv_path, source="shopee", append=append)


