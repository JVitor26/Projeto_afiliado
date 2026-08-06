"""Controle de uso das APIs de marketplace.

Existe por causa de um bloqueio real: o aplicativo do Mercado Livre foi barrado
de toda a API. O padrao que levava a isso era minerar 41 keywords a cada 8
minutos — cerca de 221 mil chamadas por mes, so de leitura.

A documentacao de bloqueio do Mercado Livre lista dois motivos que descrevem
exatamente esse padrao:

* ``EXCESSIVE_API_CALL`` — volume excessivo de chamadas. A propria doc pede
  "controles sobre os erros 400 nao previstos, ja que o excesso deles podera
  acarretar bloqueios".
* ``INTEGRATORS_DATA_INFRACTION`` — consumo apenas de leitura.

O volume e a reacao a erro sao tratados aqui. O carater de leitura nao e algo
que codigo resolva: e a natureza de um bot de afiliados.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from afiliado_bot.storage import Storage

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ThrottlePolicy:
    """Limites de uso de uma fonte."""

    interval_hours: float = 6.0
    keywords_per_run: int = 5
    max_calls_per_day: int = 0  # 0 = sem teto
    max_error_streak: int = 3
    pause_hours: float = 12.0


class SourceThrottle:
    """Decide se uma fonte pode rodar agora e quais keywords ela usa."""

    def __init__(self, storage: Storage, source: str, policy: ThrottlePolicy) -> None:
        self.storage = storage
        self.source = source
        self.policy = policy

    def check(self) -> tuple[bool, str]:
        """(pode_rodar, motivo). O motivo explica a recusa."""
        state = self.storage.get_source_state(self.source)
        now = datetime.now(timezone.utc)

        paused_until = state.get("paused_until")
        if paused_until and paused_until > now.isoformat():
            return False, f"em pausa ate {paused_until[:16].replace('T', ' ')} apos erros seguidos"

        if self.policy.max_calls_per_day:
            today = now.date().isoformat()
            if state.get("calls_day") == today and state.get("calls_today", 0) >= self.policy.max_calls_per_day:
                return False, f"teto diario atingido ({state['calls_today']}/{self.policy.max_calls_per_day} chamadas)"

        last_run = state.get("last_run_at")
        if last_run and self.policy.interval_hours > 0:
            next_run = datetime.fromisoformat(last_run) + timedelta(hours=self.policy.interval_hours)
            if now < next_run:
                falta = (next_run - now).total_seconds() / 60
                return False, f"proxima janela em {falta:.0f} min (intervalo de {self.policy.interval_hours}h)"

        return True, "ok"

    def next_keywords(self, keywords: list[str]) -> list[str]:
        """Fatia seguinte do rodizio.

        Rodar sempre as mesmas keywords desperdicaria chamadas repetindo os
        mesmos produtos; o cursor faz a lista inteira ser coberta ao longo dos
        ciclos, com um punhado por vez.
        """
        if not keywords:
            return []
        size = max(1, self.policy.keywords_per_run)
        if size >= len(keywords):
            return list(keywords)

        state = self.storage.get_source_state(self.source)
        cursor = int(state.get("keyword_cursor") or 0) % len(keywords)
        selection = [keywords[(cursor + offset) % len(keywords)] for offset in range(size)]
        return selection

    def record_run(self, *, keywords_used: int, errors: int) -> None:
        """Fecha o ciclo: avanca o cursor e liga a pausa se houver erro demais."""
        state = self.storage.get_source_state(self.source)
        now = datetime.now(timezone.utc)
        today = now.date().isoformat()

        calls_today = int(state.get("calls_today") or 0)
        calls_today = keywords_used if state.get("calls_day") != today else calls_today + keywords_used

        if errors:
            streak = int(state.get("error_streak") or 0) + 1
        else:
            streak = 0

        paused_until = state.get("paused_until")
        if streak >= self.policy.max_error_streak > 0:
            paused_until = (now + timedelta(hours=self.policy.pause_hours)).replace(microsecond=0).isoformat()
            log.warning(
                "%s: %d ciclos seguidos com erro — pausando ate %s para nao acumular erro na API",
                self.source,
                streak,
                paused_until,
            )
        elif not errors:
            paused_until = None

        self.storage.save_source_state(
            self.source,
            last_run_at=now.replace(microsecond=0).isoformat(),
            keyword_cursor=int(state.get("keyword_cursor") or 0) + keywords_used,
            error_streak=streak,
            paused_until=paused_until,
            calls_today=calls_today,
            calls_day=today,
        )

    def status(self) -> str:
        state = self.storage.get_source_state(self.source)
        allowed, reason = self.check()
        parts = [f"{self.source}: {'liberado' if allowed else 'aguardando'} ({reason})"]
        if state.get("last_run_at"):
            parts.append(f"ultima execucao: {state['last_run_at'][:16].replace('T', ' ')}")
        if state.get("calls_today"):
            parts.append(f"chamadas hoje: {state['calls_today']}")
        if state.get("error_streak"):
            parts.append(f"ciclos com erro seguidos: {state['error_streak']}")
        return " | ".join(parts)
