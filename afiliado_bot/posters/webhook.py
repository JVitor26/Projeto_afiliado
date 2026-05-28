from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from afiliado_bot.config import AppConfig
from afiliado_bot.models import PostResult, Product


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

        payload = json.dumps(
            {
                "message": message,
                "product": {
                    "id": product.id,
                    "source": product.source,
                    "external_id": product.external_id,
                    "title": product.title,
                    "price": product.price,
                    "currency": product.currency,
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
