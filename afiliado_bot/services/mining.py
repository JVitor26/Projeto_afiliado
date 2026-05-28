from __future__ import annotations

from dataclasses import dataclass, field

from afiliado_bot.clients.base import ProductProvider, ProviderError
from afiliado_bot.scoring import ProductRanker
from afiliado_bot.storage import Storage


@dataclass
class MiningReport:
    imported: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


class MiningService:
    def __init__(self, providers: list[ProductProvider], storage: Storage, ranker: ProductRanker) -> None:
        self.providers = providers
        self.storage = storage
        self.ranker = ranker

    def mine(self, keywords: list[str], *, limit_per_keyword: int) -> MiningReport:
        report = MiningReport()
        for keyword in keywords:
            for provider in self.providers:
                try:
                    products = provider.fetch(keyword, limit=limit_per_keyword)
                except ProviderError as exc:
                    report.errors.append(f"{provider.name}/{keyword}: {exc}")
                    continue

                for product in products:
                    reason = self.ranker.reject_reason(product)
                    if reason:
                        report.skipped += 1
                        continue
                    product.score = self.ranker.score(product)
                    product.id = self.storage.upsert_product(product)
                    report.imported += 1
        return report
