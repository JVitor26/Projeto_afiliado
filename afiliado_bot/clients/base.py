from __future__ import annotations

import time
from typing import Callable, Protocol, TypeVar

from afiliado_bot.models import Product


class ProviderError(RuntimeError):
    pass


class ProductProvider(Protocol):
    name: str

    def fetch(self, keyword: str, *, limit: int) -> list[Product]:
        ...


_T = TypeVar("_T")

# Códigos HTTP que valem tentar de novo (rate-limit, gateway, timeout de proxy)
_RETRYABLE_CODES = frozenset({429, 500, 502, 503, 504})


def retry_http(
    fn: Callable[[], _T],
    *,
    attempts: int = 3,
    base_delay: float = 2.0,
    retryable_codes: frozenset[int] = _RETRYABLE_CODES,
) -> _T:
    """Executa *fn* com retry exponencial para erros HTTP transitórios.

    Lança a última exceção se todos os attempts falharem.
    """
    from urllib.error import HTTPError, URLError  # local import para não criar dep circular

    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except HTTPError as exc:
            if exc.code not in retryable_codes:
                raise
            last_exc = exc
        except URLError as exc:
            last_exc = exc

        if attempt < attempts - 1:
            time.sleep(base_delay * (2 ** attempt))

    raise last_exc  # type: ignore[misc]
