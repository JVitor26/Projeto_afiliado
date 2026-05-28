from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from afiliado_bot.config import AppConfig
from afiliado_bot.models import PostResult


class WhatsAppPoster:
    """Posts offers to WhatsApp via Cloud API."""

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
            return [PostResult(channel="whatsapp", success=False, response="WhatsApp nao configurado")]

        if not self.config.whatsapp_chat_ids:
            return [PostResult(channel="whatsapp", success=False, response="WHATSAPP_CHAT_IDS nao configurado")]

        results = []
        for chat_id in self.config.whatsapp_chat_ids:
            recipient = _normalize_recipient(chat_id)
            channel = f"whatsapp:{chat_id}"
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
            results.append(self._send_message(message, product, recipient=recipient, channel=channel))
        return results

    def _send_message(self, message: str, product: object, *, recipient: str, channel: str) -> PostResult:
        try:
            url = urljoin(self.api_url, f"{self.phone_number_id}/messages")
            image_url = getattr(product, "image_url", "")

            body = message.split("\n\n")[0] if message else "Nova oferta"
            body = body[:1024] if body else "Confira esta oferta"

            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": recipient,
                "type": "template" if image_url else "text",
            }

            if image_url:
                payload["template"] = {
                    "name": "offer_template",
                    "language": {"code": "pt_BR"},
                    "components": [
                        {
                            "type": "header",
                            "parameters": [{"type": "image", "image": {"link": image_url}}],
                        },
                        {
                            "type": "body",
                            "parameters": [
                                {"type": "text", "text": body},
                            ],
                        },
                    ],
                }
            else:
                payload["text"] = {"body": body}

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


def _normalize_recipient(raw_recipient: str) -> str | None:
    recipient = raw_recipient.strip()
    if not recipient:
        return ""
    if "whatsapp.com/channel/" in recipient.lower():
        return None
    digits = re.sub(r"\D", "", recipient)
    return digits or recipient
