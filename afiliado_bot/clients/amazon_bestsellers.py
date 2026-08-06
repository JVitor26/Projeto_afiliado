"""Provider que le as listas "Mais Vendidos" da Amazon Brasil.

Diferente de :mod:`afiliado_bot.clients.amazon`, que depende de PA-API ou da
Creators API, este provider funciona apenas com a tag de associado: ele abre as
paginas publicas ``/gp/bestsellers/<categoria>`` e transforma cada card do
ranking em :class:`~afiliado_bot.models.Product`.

Regra inegociavel: sem ``AMAZON_PARTNER_TAG`` o provider fica desabilitado. Um
link da Amazon sem a tag manda trafego de graca e nao gera comissao.
"""

from __future__ import annotations

import html
import json
import logging
import random
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from afiliado_bot.config import AppConfig
from afiliado_bot.models import Product

from .base import ProviderError

log = logging.getLogger(__name__)

# A Amazon devolve 503 em rajadas curtas, entao rotacionamos o User-Agent e
# damos um intervalo entre categorias.
_USER_AGENTS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
)

# Nome legivel para as categorias usadas por padrao.
CATEGORY_LABELS = {
    "electronics": "Eletronicos",
    "computers": "Informatica",
    "videogames": "Games",
    "kitchen": "Cozinha",
    "appliances": "Eletrodomesticos",
    "home": "Casa",
    "hpc": "Saude e Cuidados Pessoais",
    "beauty": "Beleza",
    "toys": "Brinquedos",
    "sports": "Esportes",
    "automotive": "Automotivo",
    "office-products": "Escritorio",
    "pet-supplies": "Pet",
    "baby": "Bebe",
    "garden": "Casa e Jardim",
    "musical-instruments": "Instrumentos Musicais",
    "books": "Livros",
    "fashion": "Moda",
}

_FACEOUT_SPLIT = re.compile(r'(?=<div id="[A-Z0-9]{10}" class="p13n-sc-uncoverable-faceout")')
_ASIN = re.compile(r'<div id="([A-Z0-9]{10})" class="p13n-sc-uncoverable-faceout"')
# As classes da Amazon tem hash gerado no build (ex: _cDEzb_p13n-sc-price_3mJ9Z),
# entao casamos so a parte estavel do nome.
_TITLE = re.compile(r'p13n-sc-css-line-clamp-\d+[^"]*"\s*>(.*?)</div>', re.DOTALL)
_IMG_ALT = re.compile(r'<img alt="(.*?)"')
_IMG_SRC = re.compile(r'<img[^>]+src="(https://[^"]+?\.jpg)"')
_DYNAMIC_IMAGE = re.compile(r'data-a-dynamic-image="(\{.*?\})"', re.DOTALL)
_PRICE = re.compile(r'p13n-sc-price[^"]*"\s*>\s*R\$\s*([\d.,]+)\s*<')
_RATING = re.compile(r'aria-label="([\d.,]+) de 5 estrelas')
_REVIEWS = re.compile(r'aria-label="[\d.,]+ de 5 estrelas,\s*([\d.,]+)\s*(?:classifica|avalia)')
_REVIEWS_FALLBACK = re.compile(r'<span aria-hidden="true" class="a-size-small">\s*([\d.,]+)\s*</span>')
_BLOCK_MARKERS = ("api-services-support@amazon.com", "Digite os caracteres", "Robot Check")


class AmazonBestSellersClient:
    """Le o ranking "Mais Vendidos" da Amazon BR e gera produtos com tag de afiliado."""

    name = "amazon"

    def __init__(self, config: AppConfig, timeout: int = 25) -> None:
        self.config = config
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.config.amazon_partner_tag.strip())

    def fetch(self, keyword: str, *, limit: int) -> list[Product]:
        """Busca uma categoria do ranking.

        *keyword* e o slug da categoria (``electronics``, ``kitchen``...), nao um
        termo de busca: o ranking ja e a propria selecao de produtos.
        """
        if not self.enabled:
            raise ProviderError(
                "AMAZON_PARTNER_TAG vazio: sem a tag de associado o link nao gera comissao."
            )

        slug = keyword.strip().strip("/")
        if not slug:
            return []

        products: list[Product] = []
        seen: set[str] = set()
        for page in range(1, max(1, self.config.amazon_bestsellers_pages) + 1):
            if len(products) >= limit:
                break
            body = self._fetch_page(slug, page)
            for product in self._parse(body, slug, start_rank=(page - 1) * 30 + 1):
                if product.external_id in seen:
                    continue
                seen.add(product.external_id)
                products.append(product)
                if len(products) >= limit:
                    break
        return products

    def _fetch_page(self, slug: str, page: int) -> str:
        url = f"https://{self.config.amazon_marketplace}/gp/bestsellers/{slug}/"
        if page > 1:
            url = f"{url}ref=zg_bs_pg_{page}?ie=UTF8&pg={page}"

        last_error: Exception | None = None
        for attempt in range(self.config.amazon_bestsellers_attempts):
            request = Request(
                url,
                headers={
                    "User-Agent": random.choice(_USER_AGENTS),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
                    # A stdlib nao descomprime sozinha; pedimos texto puro.
                    "Accept-Encoding": "identity",
                    "Cache-Control": "no-cache",
                },
            )
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    body = response.read().decode("utf-8", errors="replace")
            except HTTPError as exc:
                last_error = exc
                if exc.code not in {429, 500, 502, 503, 504}:
                    raise ProviderError(f"Amazon bestsellers HTTP {exc.code} em {slug}") from exc
            except (URLError, OSError) as exc:
                last_error = exc
            else:
                if any(marker in body[:6000] for marker in _BLOCK_MARKERS):
                    last_error = ProviderError(f"Amazon bloqueou a leitura de {slug} (captcha)")
                else:
                    return body

            if attempt < self.config.amazon_bestsellers_attempts - 1:
                # O 503 da Amazon e aleatorio (a mesma URL falha e passa segundos
                # depois), entao o backoff cresce e leva jitter para nao bater
                # sempre no mesmo ritmo.
                backoff = self.config.amazon_bestsellers_delay * (2 ** attempt)
                time.sleep(backoff + random.uniform(0, self.config.amazon_bestsellers_delay))

        raise ProviderError(f"Amazon bestsellers falhou em {slug}: {last_error}")

    def _parse(self, body: str, slug: str, *, start_rank: int) -> list[Product]:
        blocks = _FACEOUT_SPLIT.split(body)[1:]
        category = CATEGORY_LABELS.get(slug, slug.replace("-", " ").title())
        products: list[Product] = []

        for offset, block in enumerate(blocks):
            asin_match = _ASIN.search(block)
            if not asin_match:
                continue
            asin = asin_match.group(1)

            title = _clean(_TITLE.search(block))
            if not title:
                title = _clean(_IMG_ALT.search(block))
            if not title:
                continue

            price = _money(_PRICE.search(block))
            rank = start_rank + offset
            permalink = f"https://{self.config.amazon_marketplace}/dp/{asin}"

            products.append(
                Product(
                    source=self.name,
                    external_id=asin,
                    title=title,
                    price=price,
                    currency="BRL",
                    permalink=permalink,
                    affiliate_url=build_affiliate_url(
                        asin,
                        self.config.amazon_partner_tag,
                        marketplace=self.config.amazon_marketplace,
                    ),
                    image_url=_best_image(block),
                    category=category,
                    rating=_rating(block),
                    sold_quantity=_reviews(block),
                    metadata={
                        "keyword": slug,
                        "raw_source": "amazon_bestsellers",
                        "bestseller_rank": rank,
                        "bestseller_category": category,
                    },
                )
            )
        return products


def build_affiliate_url(asin: str, partner_tag: str, *, marketplace: str = "www.amazon.com.br") -> str:
    """Monta o link de associado no mesmo formato do SiteStripe."""
    tag = partner_tag.strip()
    if not tag:
        raise ValueError("partner_tag obrigatorio para montar link de afiliado Amazon")
    return f"https://{marketplace}/dp/{asin}?tag={tag}&linkCode=ll1&language=pt_BR&ref_=as_li_ss_tl"


def _clean(match: re.Match[str] | None) -> str:
    if not match:
        return ""
    text = re.sub(r"<[^>]+>", " ", match.group(1))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _money(match: re.Match[str] | None) -> float:
    if not match:
        return 0.0
    text = match.group(1).replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return 0.0


def _rating(block: str) -> float | None:
    match = _RATING.search(block)
    if not match:
        return None
    try:
        value = float(match.group(1).replace(",", "."))
    except ValueError:
        return None
    return value if 0 < value <= 5 else None


def _reviews(block: str) -> int | None:
    match = _REVIEWS.search(block) or _REVIEWS_FALLBACK.search(block)
    if not match:
        return None
    digits = re.sub(r"[^\d]", "", match.group(1))
    return int(digits) if digits else None


def _best_image(block: str) -> str:
    """Escolhe a maior resolucao disponivel no data-a-dynamic-image."""
    dynamic = _DYNAMIC_IMAGE.search(block)
    if dynamic:
        try:
            payload = json.loads(html.unescape(dynamic.group(1)))
        except (json.JSONDecodeError, ValueError):
            payload = {}
        best_url = ""
        best_area = -1
        for url, size in payload.items():
            if not isinstance(size, list) or len(size) != 2:
                continue
            area = int(size[0]) * int(size[1])
            if area > best_area:
                best_area, best_url = area, url
        if best_url:
            return best_url

    src = _IMG_SRC.search(block)
    return src.group(1) if src else ""
