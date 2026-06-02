from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from afiliado_bot.config import AppConfig
from afiliado_bot.models import PostResult


class WhatsAppGroupPoster:
    """Envia mensagens para grupos WhatsApp via API nao-oficial (Evolution API ou Green API)."""

    channel = "whatsapp_group"

    def __init__(self, config: AppConfig, timeout: int = 20) -> None:
        self.config = config
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.config.whatsapp_group_api_url and self.config.whatsapp_group_ids)

    def post_text(self, text: str) -> list[PostResult]:
        if not self.enabled:
            return [PostResult(channel=self.channel, success=False, response="whatsapp_group nao configurado")]
        results = []
        for group_id in self.config.whatsapp_group_ids:
            results.append(self._send(group_id, text))
        return results

    def _send(self, group_id: str, text: str) -> PostResult:
        channel = f"{self.channel}:{group_id}"
        api_url = self.config.whatsapp_group_api_url.rstrip("/")
        api_type = (self.config.whatsapp_group_api_type or "evolution").lower()

        if api_type == "green":
            return self._send_green(group_id, text, channel, api_url)
        return self._send_evolution(group_id, text, channel, api_url)

    def _send_evolution(self, group_id: str, text: str, channel: str, api_url: str) -> PostResult:
        instance = self.config.whatsapp_group_instance or "default"
        url = f"{api_url}/message/sendText/{instance}"
        payload = {"number": group_id, "text": text}
        headers = {
            "Content-Type": "application/json",
            "apikey": self.config.whatsapp_group_api_key,
        }
        return self._request(url, payload, headers, channel)

    def _send_green(self, group_id: str, text: str, channel: str, api_url: str) -> PostResult:
        instance_id = self.config.whatsapp_group_instance
        api_token = self.config.whatsapp_group_api_key
        url = f"{api_url}/waInstance{instance_id}/sendMessage/{api_token}"
        payload = {"chatId": group_id, "message": text}
        headers = {"Content-Type": "application/json"}
        return self._request(url, payload, headers, channel)

    def _request(self, url: str, payload: dict[str, object], headers: dict[str, str], channel: str) -> PostResult:
        try:
            request = Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
                return PostResult(channel=channel, success=True, response=body[:300], status_code=response.status)
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return PostResult(channel=channel, success=False, response=f"HTTP {exc.code}: {body[:200]}", status_code=exc.code)
        except URLError as exc:
            return PostResult(channel=channel, success=False, response=f"Conexao: {exc.reason}")

    def list_groups(self) -> list[dict[str, object]]:
        """Retorna lista de grupos do WhatsApp para ajudar a descobrir o ID do grupo."""
        if not self.config.whatsapp_group_api_url or not self.config.whatsapp_group_api_key:
            return []
        api_url = self.config.whatsapp_group_api_url.rstrip("/")
        api_type = (self.config.whatsapp_group_api_type or "evolution").lower()

        if api_type == "green":
            return self._list_groups_green(api_url)
        return self._list_groups_evolution(api_url)

    def _list_groups_evolution(self, api_url: str) -> list[dict[str, object]]:
        instance = self.config.whatsapp_group_instance or "default"
        url = f"{api_url}/group/fetchAllGroups/{instance}?getParticipants=false"
        request = Request(url, headers={"apikey": self.config.whatsapp_group_api_key})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            if isinstance(data, list):
                return [{"id": g.get("id", ""), "name": g.get("subject", "")} for g in data]
        except Exception:
            pass
        return []

    def _list_groups_green(self, api_url: str) -> list[dict[str, object]]:
        instance_id = self.config.whatsapp_group_instance
        api_token = self.config.whatsapp_group_api_key
        url = f"{api_url}/waInstance{instance_id}/getChats/{api_token}"
        request = Request(url)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            if isinstance(data, list):
                return [
                    {"id": c.get("id", ""), "name": c.get("name", "")}
                    for c in data
                    if "@g.us" in str(c.get("id", ""))
                ]
        except Exception:
            pass
        return []
