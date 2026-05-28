from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class Product:
    source: str
    external_id: str
    title: str
    price: float
    currency: str
    permalink: str
    affiliate_url: str
    image_url: str = ""
    category: str = ""
    score: float = 0.0
    original_price: float | None = None
    rating: float | None = None
    sold_quantity: int | None = None
    free_shipping: bool = False
    captured_at: str = field(default_factory=utc_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)
    id: int | None = None

    @property
    def discount_percent(self) -> float:
        if not self.original_price or self.original_price <= self.price:
            return 0.0
        return round(((self.original_price - self.price) / self.original_price) * 100, 2)


@dataclass
class PostResult:
    channel: str
    success: bool
    response: str = ""
    status_code: int | None = None
