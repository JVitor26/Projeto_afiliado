from __future__ import annotations

import json
import logging
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from afiliado_bot.config import AppConfig
from afiliado_bot.posters.whatsapp_group import WhatsAppGroupPoster

log = logging.getLogger(__name__)


class TelegramToWhatsAppForwarder:
    """Monitora o canal Telegram e encaminha novas mensagens para grupos WhatsApp."""

    def __init__(self, config: AppConfig, poll_interval: int = 10) -> None:
        self.config = config
        self.poll_interval = poll_interval
        self._offset = 0
        self._poster = WhatsAppGroupPoster(config)

    def run_forever(self) -> None:
        if not self.config.telegram_bot_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN nao configurado no .env")
        if not self._poster.enabled:
            raise RuntimeError(
                "WhatsApp Group nao configurado. "
                "Preencha WHATSAPP_GROUP_API_URL, WHATSAPP_GROUP_API_KEY e WHATSAPP_GROUP_IDS no .env"
            )

        channels = ", ".join(self.config.telegram_chat_ids) or "(todos)"
        groups = ", ".join(self.config.whatsapp_group_ids)
        log.info("Monitorando Telegram: %s", channels)
        log.info("Encaminhando para WhatsApp: %s", groups)
        log.info("Intervalo de polling: %ds", self.poll_interval)

        while True:
            try:
                updates = self._get_updates()
                for update in updates:
                    self._process_update(update)
            except KeyboardInterrupt:
                log.info("Parado pelo usuario.")
                return
            except Exception as exc:
                log.error("Erro no loop do forwarder: %s", exc)
            time.sleep(self.poll_interval)

    def _get_updates(self) -> list[dict[str, object]]:
        params: dict[str, object] = {
            "timeout": 30,
            "allowed_updates": json.dumps(["channel_post"]),
        }
        if self._offset:
            params["offset"] = self._offset

        url = (
            f"https://api.telegram.org/bot{self.config.telegram_bot_token}"
            f"/getUpdates?{urlencode(params)}"
        )
        request = Request(url)
        try:
            with urlopen(request, timeout=35) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, json.JSONDecodeError) as exc:
            log.warning("[telegram] erro ao buscar updates: %s", exc)
            return []

        if not payload.get("ok"):
            log.warning("[telegram] resposta nao ok: %s", payload)
            return []

        updates: list[dict[str, object]] = payload.get("result", [])
        if updates:
            self._offset = int(updates[-1]["update_id"]) + 1
        return updates

    def _process_update(self, update: dict[str, object]) -> None:
        channel_post = update.get("channel_post")
        if not channel_post or not isinstance(channel_post, dict):
            return

        # Filtra pelo canal configurado
        chat = channel_post.get("chat") or {}
        if isinstance(chat, dict):
            chat_username = f"@{chat.get('username', '')}"
            chat_id = str(chat.get("id", ""))
        else:
            return

        configured = self.config.telegram_chat_ids
        if configured and chat_username not in configured and chat_id not in configured:
            return

        # Extrai texto da mensagem ou legenda de foto
        text = str(channel_post.get("text") or channel_post.get("caption") or "").strip()
        if not text:
            return

        msg_id = channel_post.get("message_id", "?")
        preview = text[:70].replace("\n", " ")
        log.info("[telegram] msg#%s: %s...", msg_id, preview)

        results = self._poster.post_text(text)
        for result in results:
            if result.success:
                log.info("  [%s] ok", result.channel)
            else:
                log.warning("  [%s] ERRO — %s", result.channel, result.response[:100])
