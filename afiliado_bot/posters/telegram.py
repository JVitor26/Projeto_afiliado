from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from afiliado_bot.config import AppConfig
from afiliado_bot.models import PostResult, Product


MAX_PHOTO_CAPTION_LENGTH = 1024


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
        channel = f"{self.channel}:{chat_id}"
        image_url = product.image_url.strip()
        if not image_url:
            return self._send_message(chat_id, message)

        photo_payload = {
            "chat_id": chat_id,
            "photo": image_url,
        }
        if len(message) <= MAX_PHOTO_CAPTION_LENGTH:
            photo_payload["caption"] = message
            if self.config.telegram_parse_mode:
                photo_payload["parse_mode"] = self.config.telegram_parse_mode
            photo_result = self._request("sendPhoto", photo_payload, channel)
            if photo_result.success:
                return photo_result
            message_result = self._send_message(chat_id, message)
            return self._fallback_result(photo_result, message_result)

        photo_result = self._request("sendPhoto", photo_payload, channel)
        if not photo_result.success:
            message_result = self._send_message(chat_id, message)
            return self._fallback_result(photo_result, message_result)

        message_result = self._send_message(chat_id, message)
        if message_result.success:
            return PostResult(
                channel=channel,
                success=True,
                response=_compact_response(photo_result.response, message_result.response),
                status_code=message_result.status_code,
            )
        return PostResult(
            channel=channel,
            success=False,
            response=_compact_response("photo sent, message failed", message_result.response),
            status_code=message_result.status_code,
        )

    def _send_message(self, chat_id: str, message: str) -> PostResult:
        payload = {
            "chat_id": chat_id,
            "text": message,
            "disable_web_page_preview": str(self.config.telegram_disable_web_page_preview).lower(),
        }
        if self.config.telegram_parse_mode:
            payload["parse_mode"] = self.config.telegram_parse_mode
        return self._request("sendMessage", payload, f"{self.channel}:{chat_id}")

    def _request(self, method: str, payload: dict[str, str], channel: str) -> PostResult:
        body = urlencode(payload).encode("utf-8")
        request = Request(
            f"https://api.telegram.org/bot{self.config.telegram_bot_token}/{method}",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                response_body = response.read().decode("utf-8", errors="replace")
                return PostResult(
                    channel=channel,
                    success=True,
                    response=response_body[:500],
                    status_code=response.status,
                )
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            return PostResult(
                channel=channel,
                success=False,
                response=error_body[:500],
                status_code=exc.code,
            )
        except URLError as exc:
            return PostResult(
                channel=channel,
                success=False,
                response=json.dumps({"error": str(exc.reason)}),
            )

    def _fallback_result(self, photo_result: PostResult, message_result: PostResult) -> PostResult:
        if message_result.success:
            return PostResult(
                channel=message_result.channel,
                success=True,
                response=_compact_response("sendPhoto failed", photo_result.response, message_result.response),
                status_code=message_result.status_code,
            )
        return PostResult(
            channel=message_result.channel,
            success=False,
            response=_compact_response("sendPhoto failed", photo_result.response, message_result.response),
            status_code=message_result.status_code or photo_result.status_code,
        )


def _compact_response(*parts: str) -> str:
    return " | ".join(part for part in parts if part)[:500]
