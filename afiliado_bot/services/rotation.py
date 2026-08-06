"""Rodizio de lojas: uma loja por execucao, em vez de todas de uma vez.

Minerar todas as fontes em toda execucao tem tres problemas: o ciclo fica
longo, cada marketplace recebe muito mais chamadas do que precisa, e uma loja
lenta atrasa as outras. Como o ranking e as ofertas nao mudam de 8 em 8 minutos,
basta visitar uma loja por vez e girar.

Cada loja mantem seus proprios limites (:mod:`afiliado_bot.services.throttle`).
O rodizio so escolhe de quem e a vez; quem nao esta pronto e pulado sem gastar
a vez de ninguem.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from afiliado_bot.services.throttle import SourceThrottle
from afiliado_bot.storage import Storage

log = logging.getLogger(__name__)

# Cursor do rodizio mora no source_state sob esta chave reservada.
_CURSOR_KEY = "_rotation"


@dataclass
class StoreSlot:
    """Uma loja no rodizio."""

    name: str
    label: str
    ready: bool
    throttle: SourceThrottle | None = None
    reason: str = ""


@dataclass
class RotationPick:
    chosen: StoreSlot | None
    skipped: list[tuple[str, str]]


class StoreRotation:
    def __init__(self, storage: Storage, slots: list[StoreSlot]) -> None:
        self.storage = storage
        self.slots = slots

    def pick(self) -> RotationPick:
        """Escolhe a loja da vez e avanca o cursor.

        Percorre a partir do cursor e devolve a primeira loja pronta. O cursor
        para logo depois dela, entao a proxima execucao comeca da seguinte —
        e nenhuma loja monopoliza o rodizio.
        """
        skipped: list[tuple[str, str]] = []
        if not self.slots:
            return RotationPick(None, skipped)

        state = self.storage.get_source_state(_CURSOR_KEY)
        cursor = int(state.get("keyword_cursor") or 0) % len(self.slots)

        for offset in range(len(self.slots)):
            index = (cursor + offset) % len(self.slots)
            slot = self.slots[index]

            if not slot.ready:
                skipped.append((slot.label, slot.reason or "nao configurada"))
                continue

            if slot.throttle is not None:
                allowed, reason = slot.throttle.check()
                if not allowed:
                    skipped.append((slot.label, reason))
                    continue

            self.storage.save_source_state(_CURSOR_KEY, keyword_cursor=index + 1)
            return RotationPick(slot, skipped)

        # Ninguem pronto: o cursor nao anda, para nao pular a vez de quem so
        # estava esperando a janela abrir.
        return RotationPick(None, skipped)

    def preview(self) -> list[str]:
        """Ordem a partir da proxima vez, para inspecao."""
        if not self.slots:
            return []
        state = self.storage.get_source_state(_CURSOR_KEY)
        cursor = int(state.get("keyword_cursor") or 0) % len(self.slots)
        return [self.slots[(cursor + offset) % len(self.slots)].label for offset in range(len(self.slots))]
