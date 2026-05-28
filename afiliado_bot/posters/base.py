from __future__ import annotations

from typing import Protocol

from afiliado_bot.models import PostResult, Product


class Poster(Protocol):
    channel: str

    def post(self, message: str, product: Product) -> list[PostResult]:
        ...
