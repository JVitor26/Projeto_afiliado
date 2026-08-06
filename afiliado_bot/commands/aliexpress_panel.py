"""Le ofertas do AliExpress com o plugin de afiliado, usando navegador.

Usado quando a API de afiliados nao foi liberada para a conta. Automatiza o que
se faz na mao: buscar produtos, abrir cada um e clicar em "Get link" para pegar
o ``s.click.aliexpress.com/e/...`` ja com o seu Tracking ID.

Diferente da Shopee, o AliExpress nao tem uma lista de ofertas com botao de link
em cada card: o botao vive **na pagina do produto**, no cabecalho do plugin de
afiliado. Por isso a coleta abre um produto por vez.

Fluxo:
    1. ``aliexpress-panel-login`` guarda a sessao (login + plugin de afiliado).
    2. ``aliexpress-panel-import`` busca por palavra-chave e coleta os links.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from .panel_common import (
    PanelError,
    PanelOffer,
    PanelReport,
    money,
    playwright_or_explain,
    sold_to_int,
)

log = logging.getLogger(__name__)

HOME_URL = "https://www.aliexpress.com/"
SEARCH_URL = "https://www.aliexpress.com/w/wholesale-{keyword}.html"

# Seletores conferidos no DevTools. O plugin de afiliado so aparece para conta
# logada no programa; sem ele nao ha botao de link.
SEL_CARD = "a[href*='/item/']"
SEL_GETLINK_BTN = "button.get-link-pro-button"
SEL_BALLOON = ".get-link-pro-balloon"
SEL_PLUGIN_HEADER = "#aff-detail-plugin-header, .aff-detail-plugin-header"

_TRACKING_LINK = re.compile(r"https://s\.click\.aliexpress\.com/e/_[A-Za-z0-9]+")
_ITEM_ID = re.compile(r"/item/(\d+)\.html")
_SOLD = re.compile(r"([\d.,]+)\s*\+?\s*sold", re.IGNORECASE)
_RATING = re.compile(r"\b([0-5][.,]\d)\b")
_COMMISSION = re.compile(r"([\d.,]+)\s*%")


def save_session(session_path: Path, *, timeout_seconds: int = 300) -> None:
    """Abre o navegador para login manual e guarda a sessao."""
    sync_playwright = playwright_or_explain()
    session_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(locale="pt-BR")
        page = context.new_page()
        page.goto(HOME_URL)

        print("Entre na sua conta AliExpress na janela que abriu.")
        print("Abra um produto qualquer e confirme que o painel de afiliado")
        print("(com 'Get link' e a comissao) aparece no topo da pagina.")
        input("Quando estiver logado e com o painel visivel, pressione ENTER aqui... ")

        context.storage_state(path=str(session_path))
        browser.close()

    print(f"Sessao salva em {session_path}")
    print("Esse arquivo e credencial: nao commite e nao compartilhe.")


def collect_offers(
    session_path: Path,
    keyword: str,
    *,
    limit: int = 10,
    headless: bool = True,
    delay_ms: int = 1200,
) -> PanelReport:
    """Busca por *keyword* e pega o link de afiliado de cada produto."""
    if not session_path.exists():
        raise PanelError(
            f"Sessao nao encontrada em {session_path}.\n"
            "Rode primeiro: python -m afiliado_bot aliexpress-panel-login"
        )

    sync_playwright = playwright_or_explain()
    report = PanelReport()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(storage_state=str(session_path), locale="pt-BR")
        page = context.new_page()

        url = SEARCH_URL.format(keyword=keyword.replace(" ", "-"))
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        # A busca carrega por scroll; sem isso vem meia duzia de itens
        for _ in range(3):
            page.mouse.wheel(0, 2400)
            page.wait_for_timeout(900)

        product_urls = _collect_product_urls(page, limit)
        log.info("produtos encontrados na busca: %d", len(product_urls))
        if not product_urls:
            browser.close()
            raise PanelError(
                f"Nenhum produto encontrado para '{keyword}'. "
                "A sessao pode ter expirado ou o layout da busca mudou."
            )

        for index, product_url in enumerate(product_urls, start=1):
            if report.collected >= limit:
                break
            try:
                offer = _read_product(page, product_url, delay_ms=delay_ms)
            except Exception as exc:  # noqa: BLE001 - um produto ruim nao para a coleta
                report.errors.append(f"produto {index}: {exc}")
                continue

            if not offer.affiliate_url:
                report.without_link += 1
                report.errors.append(f"{(offer.title or product_url)[:44]}: sem link de afiliado")
                continue

            report.offers.append(offer)
            report.collected += 1
            log.info("[%d/%d] %s", report.collected, limit, offer.title[:56])

        browser.close()

    return report


def _collect_product_urls(page, limit: int) -> list[str]:
    """Junta os links de produto da busca, sem repetir o mesmo item."""
    urls: list[str] = []
    seen: set[str] = set()

    for anchor in page.query_selector_all(SEL_CARD):
        href = anchor.get_attribute("href") or ""
        match = _ITEM_ID.search(href)
        if not match:
            continue
        item_id = match.group(1)
        if item_id in seen:
            continue
        seen.add(item_id)
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = "https://www.aliexpress.com" + href
        urls.append(href.split("?")[0])
        # Sobra folga porque parte dos produtos nao rende link
        if len(urls) >= limit * 3:
            break

    return urls


def _read_product(page, product_url: str, *, delay_ms: int) -> PanelOffer:
    offer = PanelOffer(product_url=product_url)
    page.goto(product_url, wait_until="domcontentloaded")
    page.wait_for_timeout(delay_ms)

    title = page.query_selector("h1")
    if title:
        offer.title = (title.inner_text() or "").strip()

    body = page.inner_text("body")

    prices = re.findall(r"R\$\s*[\d.,]+", body[:4000])
    if prices:
        offer.price = money(prices[0])
        for candidate in prices[1:4]:
            value = money(candidate)
            if value > offer.price:
                offer.original_price = value
                break

    sold = _SOLD.search(body[:4000])
    if sold:
        offer.sold_quantity = sold_to_int(sold.group(1))

    image = page.query_selector("meta[property='og:image']")
    if image:
        offer.image_url = image.get_attribute("content") or ""
    if not offer.image_url:
        img = page.query_selector("img[src*='alicdn.com']")
        if img:
            src = img.get_attribute("src") or ""
            offer.image_url = ("https:" + src) if src.startswith("//") else src

    header = page.query_selector(SEL_PLUGIN_HEADER)
    if header:
        commission = _COMMISSION.search(header.inner_text() or "")
        if commission:
            # Guardado como fracao (7.0% -> 0.07), igual ao resto do sistema
            offer.commission_rate = round(money(commission.group(1)) / 100, 4)

    offer.affiliate_url = _get_tracking_link(page, delay_ms=delay_ms)
    return offer


def _get_tracking_link(page, *, delay_ms: int) -> str:
    """Clica em "Get link" e le o s.click.aliexpress.com do balao."""
    button = page.query_selector(SEL_GETLINK_BTN)
    if not button:
        return ""

    try:
        button.click()
        page.wait_for_selector(SEL_BALLOON, timeout=10000)
        page.wait_for_timeout(delay_ms)

        balloon = page.query_selector(SEL_BALLOON)
        if not balloon:
            return ""

        # O link aparece num input e tambem no HTML pronto da imagem
        for field_el in balloon.query_selector_all("input, textarea"):
            value = field_el.input_value() or field_el.get_attribute("value") or ""
            found = _TRACKING_LINK.search(value)
            if found:
                return found.group(0)

        found = _TRACKING_LINK.search(balloon.inner_text() or "")
        return found.group(0) if found else ""
    except Exception as exc:  # noqa: BLE001
        log.debug("falha ao pegar tracking link: %s", exc)
        return ""
    finally:
        # Fecha o balao para nao atrapalhar o proximo produto
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)
        except Exception:  # noqa: BLE001
            pass
