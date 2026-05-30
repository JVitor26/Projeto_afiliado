"""
Utilitários de imagem: download + marca d'água PromoLink Brasil.

Requer Pillow:
    pip install Pillow
    # ou no GitHub Actions: pip install Pillow

Se Pillow não estiver instalado, as funções retornam None sem quebrar o bot.
"""
from __future__ import annotations

import io
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

BASE_DIR = Path(__file__).resolve().parent.parent

# Caminho padrão da logo – ajuste se mover o arquivo
LOGO_PATH = BASE_DIR / "imagens" / "logo, promolink.jpg"


def watermark_image(
    product_image_url: str,
    *,
    logo_path: Path | None = None,
    logo_scale: float = 0.28,   # logo ocupa 28% da largura da imagem
    opacity: float = 0.90,       # 90% de opacidade
    position: str = "bottom-right",  # bottom-right | bottom-left | top-right | top-left
) -> bytes | None:
    """
    Baixa a imagem do produto e aplica a logo PromoLink no canto escolhido.

    Retorna bytes JPEG da imagem composta, ou None se:
    - Pillow não estiver instalado
    - O download da imagem falhar
    - A logo não existir no caminho configurado
    """
    try:
        from PIL import Image
    except ImportError:
        return None

    logo_file = logo_path or LOGO_PATH
    if not logo_file.exists():
        return None

    if not product_image_url or not product_image_url.startswith("http"):
        return None

    # ── Download da imagem do produto ─────────────────────────
    try:
        req = Request(
            product_image_url,
            headers={"User-Agent": "Mozilla/5.0 afiliado-bot/0.1"},
        )
        with urlopen(req, timeout=14) as resp:
            product_bytes = resp.read()
    except Exception:
        return None

    # ── Composição ────────────────────────────────────────────
    try:
        product_img = Image.open(io.BytesIO(product_bytes)).convert("RGBA")
        logo_img   = Image.open(logo_file).convert("RGBA")

        pw, ph = product_img.size

        # Redimensionar logo
        lw = max(60, int(pw * logo_scale))
        lh = int(lw * logo_img.height / logo_img.width)
        logo_resized = logo_img.resize((lw, lh), Image.LANCZOS)

        # Aplicar opacidade (ajusta só o canal alpha)
        if opacity < 1.0:
            r, g, b, a = logo_resized.split()
            a = a.point(lambda v: int(v * opacity))
            logo_resized = Image.merge("RGBA", (r, g, b, a))

        # Calcular posição
        margin = max(8, int(pw * 0.025))
        if position == "bottom-right":
            x, y = pw - lw - margin, ph - lh - margin
        elif position == "bottom-left":
            x, y = margin, ph - lh - margin
        elif position == "top-right":
            x, y = pw - lw - margin, margin
        else:  # top-left
            x, y = margin, margin

        # Compor e salvar
        out_img = product_img.copy()
        out_img.paste(logo_resized, (x, y), logo_resized)

        buf = io.BytesIO()
        out_img.convert("RGB").save(buf, format="JPEG", quality=88, optimize=True)
        return buf.getvalue()

    except Exception:
        return None
