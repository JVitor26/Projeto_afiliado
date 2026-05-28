from __future__ import annotations

from typing import Protocol

from afiliado_bot.models import Product


class ProviderError(RuntimeError):
    pass


class ProductProvider(Protocol):
    name: str

    def fetch(self, keyword: str, *, limit: int) -> list[Product]:
        ...
