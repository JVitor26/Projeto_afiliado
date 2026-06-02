from __future__ import annotations

import dataclasses
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from afiliado_bot.config import AppConfig
from afiliado_bot.models import PostResult, Product


_TECH_TERMS = re.compile(
    r"""
    smart\s*tv | televisor | tela\s+\d | monitor\s+\d | monitor\s+gamer |
    notebook | laptop | computador | desktop | pc\s+gamer | workstation |
    teclado | mousepad | webcam | placa\s+de\s+v[ií]deo | gpu |
    processador | mem[oó]ria\s+ram | \bram\b | \bssd\b | \bnvme\b |
    hd\s+externo | pendrive | cart[aã]o\s+de\s+mem[oó]ria |
    gabinete | cooler | water\s+cooler |
    celular | smartphone | iphone | samsung\s+galaxy | \bxiaomi\b | \bmotorola\b |
    \btablet\b | \bipad\b |
    headset | headphone | airpods | fone\s+(de\s+ouvido|bluetooth|sem\s+fio) |
    caixa\s+de\s+som | soundbar | home\s+theater | subwoofer |
    playstation | \bps5\b | \bps4\b | \bxbox\b | nintendo\s+switch | controle\s+gamer | console |
    \bdrone\b | c[aâ]mera\s+(digital|dslr|mirrorless|de\s+a[çc][aã]o) |
    roteador | \bmodem\b | wi[-\s]fi\s+\d |
    smartwatch | rel[oó]gio\s+smart | pulseira\s+fitness |
    projetor | impressora | scanner | no[-\s]break |
    chromecast | apple\s+tv | fire\s+stick | fire\s+tv |
    power\s+bank | carregador\s+(wireless|r[aá]pido|sem\s+fio) |
    \bhdmi\b | \busb[-\s]c\b | \bthunderbolt\b |
    placa[-\s]m[aã]e | fonte\s+pc | fonte\s+atx |
    mouse\s+gamer | \bmouse\b | teclado\s+mec[aâ]nico |
    cadeira\s+gamer | mesa\s+gamer |
    tv\s+\d{2} | \btv\s+(4k|8k|oled|qled|led)\b | \b4k\b.*tv | tv\b.*\b4k
    """,
    re.IGNORECASE | re.VERBOSE,
)


MAX_PHOTO_CAPTION_LENGTH = 1024
_MULTIPART_BOUNDARY = "----PromoLinkBoundary42x"


class TelegramPoster:
    channel = "telegram"

    def __init__(self, config: AppConfig, timeout: int = 20) -> None:
        self.config = config
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.config.telegram_bot_token and self.config.telegram_chat_ids)

    def post(self, message: str, product: Product) -> list[PostResult]:
        if not self.enabled:
            return [PostResult(channel=self.channel, success=False, response="telegram not configured")]

        results: list[PostResult] = []
        for chat_id in self.config.telegram_chat_ids:
            results.append(self._post_to_chat(chat_id, message, product))
        return results

    def _post_to_chat(self, chat_id: str, message: str, product: Product) -> PostResult:
        image_url = (product.image_url or "").strip()
        if not image_url:
            return self._send_message(chat_id, message)

        # Tenta aplicar a logo PromoLink à imagem antes de enviar
        watermarked = _try_watermark(image_url)
        if watermarked:
            photo_result = self._send_photo_bytes(chat_id, watermarked, message)
            if photo_result.success:
                # Se a mensagem é longa, manda o texto separado
                if len(message) > MAX_PHOTO_CAPTION_LENGTH:
                    self._send_message(chat_id, message)
                return photo_result
            # Fallback para URL se upload falhar
        return self._post_with_url(chat_id, message, image_url)

    def _post_with_url(self, chat_id: str, message: str, image_url: str) -> PostResult:
        """Envia foto via URL (sem watermark) com fallback para texto simples."""
        photo_payload = {"chat_id": chat_id, "photo": image_url}
        if len(message) <= MAX_PHOTO_CAPTION_LENGTH:
            photo_payload["caption"] = message
            if self.config.telegram_parse_mode:
                photo_payload["parse_mode"] = self.config.telegram_parse_mode
            photo_result = self._request("sendPhoto", photo_payload, chat_id)
            if photo_result.success:
                return photo_result
            message_result = self._send_message(chat_id, message)
            return _fallback_result(photo_result, message_result)

        photo_result = self._request("sendPhoto", photo_payload, chat_id)
        if not photo_result.success:
            return _fallback_result(photo_result, self._send_message(chat_id, message))

        message_result = self._send_message(chat_id, message)
        return PostResult(
            channel=message_result.channel,
            success=True,
            response=_compact_response(photo_result.response, message_result.response),
            status_code=message_result.status_code,
        )

    def _send_photo_bytes(self, chat_id: str, image_bytes: bytes, caption: str) -> PostResult:
        """Envia imagem como upload multipart/form-data (para imagens com watermark)."""
        channel = f"{self.channel}:{chat_id}"
        b = _MULTIPART_BOUNDARY.encode()

        def field(name: str, value: str) -> bytes:
            return (
                b"--" + b + b"\r\n"
                b'Content-Disposition: form-data; name="' + name.encode() + b'"\r\n\r\n'
                + value.encode("utf-8") + b"\r\n"
            )

        body = field("chat_id", chat_id)

        short_caption = len(caption) <= MAX_PHOTO_CAPTION_LENGTH
        if short_caption:
            body += field("caption", caption)
            if self.config.telegram_parse_mode:
                body += field("parse_mode", self.config.telegram_parse_mode)

        # Parte da imagem
        body += (
            b"--" + b + b"\r\n"
            b'Content-Disposition: form-data; name="photo"; filename="produto.jpg"\r\n'
            b"Content-Type: image/jpeg\r\n\r\n"
            + image_bytes
            + b"\r\n"
            + b"--" + b + b"--\r\n"
        )

        request = Request(
            f"https://api.telegram.org/bot{self.config.telegram_bot_token}/sendPhoto",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={_MULTIPART_BOUNDARY}"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                resp_body = response.read().decode("utf-8", errors="replace")
                result = PostResult(channel=channel, success=True, response=resp_body[:500], status_code=response.status)
        except HTTPError as exc:
            err = exc.read().decode("utf-8", errors="replace")
            result = PostResult(channel=channel, success=False, response=err[:500], status_code=exc.code)
        except URLError as exc:
            result = PostResult(channel=channel, success=False, response=str(exc.reason))

        # Se caption foi incluída e upload funcionou, não precisa mandar mensagem separada
        if result.success and not short_caption:
            self._send_message(chat_id, caption)

        return result

    def _send_message(self, chat_id: str, message: str) -> PostResult:
        payload = {
            "chat_id": chat_id,
            "text": message,
            "disable_web_page_preview": str(self.config.telegram_disable_web_page_preview).lower(),
        }
        if self.config.telegram_parse_mode:
            payload["parse_mode"] = self.config.telegram_parse_mode
        return self._request("sendMessage", payload, chat_id)

    def _request(self, method: str, payload: dict[str, str], chat_id: str) -> PostResult:
        channel = f"{self.channel}:{chat_id}"
        body = urlencode(payload).encode("utf-8")
        request = Request(
            f"https://api.telegram.org/bot{self.config.telegram_bot_token}/{method}",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                resp_body = response.read().decode("utf-8", errors="replace")
                return PostResult(channel=channel, success=True, response=resp_body[:500], status_code=response.status)
        except HTTPError as exc:
            err = exc.read().decode("utf-8", errors="replace")
            return PostResult(channel=channel, success=False, response=err[:500], status_code=exc.code)
        except URLError as exc:
            return PostResult(channel=channel, success=False, response=json.dumps({"error": str(exc.reason)}))


def _try_watermark(image_url: str) -> bytes | None:
    """Tenta aplicar watermark PromoLink. Retorna None se Pillow não disponível ou falhar."""
    try:
        from afiliado_bot.image_utils import watermark_image
        return watermark_image(image_url)
    except Exception:
        return None


def _fallback_result(photo_result: PostResult, message_result: PostResult) -> PostResult:
    if message_result.success:
        return PostResult(
            channel=message_result.channel,
            success=True,
            response=_compact_response("photo failed", photo_result.response, message_result.response),
            status_code=message_result.status_code,
        )
    return PostResult(
        channel=message_result.channel,
        success=False,
        response=_compact_response("photo+message failed", photo_result.response, message_result.response),
        status_code=message_result.status_code or photo_result.status_code,
    )


def _compact_response(*parts: str) -> str:
    return " | ".join(p for p in parts if p)[:500]


def _is_tech_product(product: Product) -> bool:
    text = f"{product.title} {product.category}".lower()
    return bool(_TECH_TERMS.search(text))


class TechTelegramPoster:
    """Envia apenas para TELEGRAM_TECH_CHAT_IDS e somente produtos de tecnologia.

    Usa TELEGRAM_TECH_BOT_TOKEN se configurado; caso contrário usa o bot principal.
    """

    channel = "telegram_tech"

    def __init__(self, config: AppConfig, timeout: int = 20) -> None:
        token = config.telegram_tech_bot_token or config.telegram_bot_token
        tech_config = dataclasses.replace(
            config,
            telegram_bot_token=token,
            telegram_chat_ids=config.telegram_tech_chat_ids,
        )
        self._inner = TelegramPoster(tech_config, timeout)

    @property
    def enabled(self) -> bool:
        return self._inner.enabled

    def post(self, message: str, product: Product) -> list[PostResult]:
        if not _is_tech_product(product):
            return []
        return self._inner.post(message, product)
