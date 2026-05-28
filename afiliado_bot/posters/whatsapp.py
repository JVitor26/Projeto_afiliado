from __future__ import annotations

from html import unescape
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from afiliado_bot.config import AppConfig
from afiliado_bot.models import PostResult


class WhatsAppPoster:
    """Posts offers to WhatsApp via Cloud API."""

    channel = "whatsapp"
    max_image_caption_length = 1024
    max_text_length = 4096

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.phone_number_id = config.whatsapp_phone_number_id
        self.access_token = config.whatsapp_access_token
        api_version = config.whatsapp_graph_api_version.strip() or "v25.0"
        if not api_version.startswith("v"):
            api_version = f"v{api_version}"
        self.api_url = f"https://graph.facebook.com/{api_version}/"

    @property
    def enabled(self) -> bool:
        return bool(self.phone_number_id and self.access_token)

    def post(self, message: str, product: object) -> list[PostResult]:
        if not self.enabled:
            return [PostResult(channel=self.channel, success=False, response="WhatsApp nao configurado")]

        if not self.config.whatsapp_chat_ids:
            return [PostResult(channel=self.channel, success=False, response="WHATSAPP_CHAT_IDS nao configurado")]

        results = []
        for chat_id in self.config.whatsapp_chat_ids:
            recipient = _normalize_recipient(chat_id)
            channel = f"{self.channel}:{chat_id}"
            if recipient is None:
                results.append(
                    PostResult(
                        channel=channel,
                        success=False,
                        response=(
                            "Canal do WhatsApp nao e destinatario da Cloud API oficial. "
                            "Use um numero com codigo do pais ou SOCIAL_WEBHOOK_URLS."
                        ),
                    )
                )
                continue
            results.append(self._post_to_recipient(recipient, message, product, channel=channel))
        return results

    def _post_to_recipient(self, recipient: str, message: str, product: object, *, channel: str) -> PostResult:
        text = _format_for_whatsapp(message)
        image_url = str(getattr(product, "image_url", "") or "").strip()
        if not image_url:
            return self._send_text(recipient, text, channel=channel)

        if len(text) <= self.max_image_caption_length:
            image_result = self._send_image(recipient, image_url, caption=text, channel=channel)
            if image_result.success:
                return image_result
            text_result = self._send_text(recipient, text, channel=channel)
            return _fallback_result("image failed", image_result, text_result)

        image_result = self._send_image(recipient, image_url, caption="", channel=channel)
        if not image_result.success:
            text_result = self._send_text(recipient, text, channel=channel)
            return _fallback_result("image failed", image_result, text_result)

        text_result = self._send_text(recipient, text, channel=channel)
        if text_result.success:
            return PostResult(
                channel=channel,
                success=True,
                response=_compact_response(image_result.response, text_result.response),
                status_code=text_result.status_code,
            )
        return PostResult(
            channel=channel,
            success=False,
            response=_compact_response("image sent, message failed", text_result.response),
            status_code=text_result.status_code,
        )

    def _send_text(self, recipient: str, text: str, *, channel: str) -> PostResult:
        body = (text or "Nova oferta")[: self.max_text_length]
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "text",
            "text": {"preview_url": True, "body": body},
        }
        return self._request(payload, channel)

    def _send_image(self, recipient: str, image_url: str, *, caption: str, channel: str) -> PostResult:
        image_payload = {"link": image_url}
        if caption:
            image_payload["caption"] = caption[: self.max_image_caption_length]
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "image",
            "image": image_payload,
        }
        return self._request(payload, channel)

    def _request(self, payload: dict[str, object], channel: str) -> PostResult:
        try:
            url = urljoin(self.api_url, f"{self.phone_number_id}/messages")
            request = Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json",
                    "User-Agent": "afiliado-bot/0.1",
                },
                method="POST",
            )

            with urlopen(request, timeout=20) as response:
                result = json.loads(response.read().decode("utf-8"))
                return PostResult(
                    channel=channel,
                    success=result.get("messages") is not None,
                    response=json.dumps(result),
                    status_code=response.status,
                )
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return PostResult(channel=channel, success=False, response=f"HTTP {exc.code}: {body[:200]}", status_code=exc.code)
        except URLError as exc:
            return PostResult(channel=channel, success=False, response=f"Erro de conexao: {exc.reason}")
        except Exception as exc:
            return PostResult(channel=channel, success=False, response=f"Erro: {str(exc)[:200]}")


def _format_for_whatsapp(message: str) -> str:
    text = message or "Nova oferta"
    text = re.sub(r"<b>(.*?)</b>", r"*\1*", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<strong>(.*?)</strong>", r"*\1*", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<s>(.*?)</s>", r"~\1~", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<strike>(.*?)</strike>", r"~\1~", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    return unescape(text).strip() or "Nova oferta"


def _normalize_recipient(raw_recipient: str) -> str | None:
    recipient = raw_recipient.strip()
    if not recipient:
        return ""
    if "whatsapp.com/channel/" in recipient.lower():
        return None
    digits = re.sub(r"\D", "", recipient)
    return digits or recipient


def _fallback_result(reason: str, first_result: PostResult, second_result: PostResult) -> PostResult:
    if second_result.success:
        return PostResult(
            channel=second_result.channel,
            success=True,
            response=_compact_response(reason, first_result.response, second_result.response),
            status_code=second_result.status_code,
        )
    return PostResult(
        channel=second_result.channel,
        success=False,
        response=_compact_response(reason, first_result.response, second_result.response),
        status_code=second_result.status_code or first_result.status_code,
    )


def _compact_response(*parts: str) -> str:
    return " | ".join(part for part in parts if part)[:500]
