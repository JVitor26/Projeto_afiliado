from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from afiliado_bot.config import AppConfig
from afiliado_bot.models import PostResult, Product

from .formatting import format_for_whatsapp


class WebhookPoster:
    channel = "webhook"

    def __init__(self, config: AppConfig, timeout: int = 20) -> None:
        self.config = config
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.config.webhook_urls)

    def post(self, message: str, product: Product) -> list[PostResult]:
        if not self.enabled:
            return [PostResult(channel=self.channel, success=False, response="webhook not configured")]

        whatsapp_message = format_for_whatsapp(message)
        whatsapp_channel = self.config.whatsapp_channel_url.strip()
        payload = json.dumps(
            {
                "message": message,
                "message_text": whatsapp_message,
                "target": {
                    "type": "whatsapp_channel" if whatsapp_channel else "external_webhook",
                    "url": whatsapp_channel,
                },
                "whatsapp_channel": {
                    "url": whatsapp_channel,
                    "send_mode": "image" if product.image_url else "text",
                    "text": whatsapp_message,
                    "image_url": product.image_url,
                },
                "product": {
                    "id": product.id,
                    "source": product.source,
                    "external_id": product.external_id,
                    "title": product.title,
                    "price": product.price,
                    "original_price": product.original_price,
                    "discount_percent": product.discount_percent,
                    "currency": product.currency,
                    "permalink": product.permalink,
                    "affiliate_url": product.affiliate_url,
                    "image_url": product.image_url,
                    "category": product.category,
                    "score": product.score,
                },
            },
            ensure_ascii=False,
        ).encode("utf-8")

        results: list[PostResult] = []
        for index, url in enumerate(self.config.webhook_urls, start=1):
            request = Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json", "User-Agent": "afiliado-bot/0.1"},
                method="POST",
            )
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    body = response.read().decode("utf-8", errors="replace")
                    results.append(
                        PostResult(
                            channel=f"{self.channel}:{index}",
                            success=200 <= response.status < 300,
                            response=body[:500],
                            status_code=response.status,
                        )
                    )
            except HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                results.append(
                    PostResult(
                        channel=f"{self.channel}:{index}",
                        success=False,
                        response=body[:500],
                        status_code=exc.code,
                    )
                )
            except URLError as exc:
                results.append(
                    PostResult(channel=f"{self.channel}:{index}", success=False, response=str(exc.reason))
                )
        return results
