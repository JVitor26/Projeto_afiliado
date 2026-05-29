from __future__ import annotations

import concurrent.futures
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

        # Paralelizar por keyword
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(keywords), 4)) as executor:
            futures = {
                executor.submit(self._mine_keyword, keyword, limit_per_keyword): keyword
                for keyword in keywords
            }

            for future in concurrent.futures.as_completed(futures, timeout=300):
                keyword = futures[future]
                try:
                    partial_report = future.result()
                    report.imported += partial_report.imported
                    report.skipped += partial_report.skipped
                    report.errors.extend(partial_report.errors)
                except Exception as exc:
                    report.errors.append(f"Erro ao processar keyword '{keyword}': {exc}")

        return report

    def _mine_keyword(self, keyword: str, limit_per_keyword: int) -> MiningReport:
        report = MiningReport()

        # Paralelizar providers para a mesma keyword
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(self.providers), 5)) as executor:
            futures = {
                executor.submit(self._fetch_and_process, provider, keyword, limit_per_keyword): provider.name
                for provider in self.providers
            }

            for future in concurrent.futures.as_completed(futures, timeout=60):
                provider_name = futures[future]
                try:
                    partial_report = future.result()
                    report.imported += partial_report.imported
                    report.skipped += partial_report.skipped
                    report.errors.extend(partial_report.errors)
                except Exception as exc:
                    report.errors.append(f"{provider_name}/{keyword}: {exc}")

        return report

    def _fetch_and_process(self, provider: ProductProvider, keyword: str, limit: int) -> MiningReport:
        report = MiningReport()
        try:
            products = provider.fetch(keyword, limit=limit)
        except ProviderError as exc:
            report.errors.append(f"{provider.name}/{keyword}: {exc}")
            return report

        # Batch process products para melhorar performance
        products_to_insert = []
        for product in products:
            reason = self.ranker.reject_reason(product)
            if reason:
                report.skipped += 1
                continue
            product.score = self.ranker.score(product)
            products_to_insert.append(product)

        # Batch insert no banco
        for product in products_to_insert:
            try:
                product.id = self.storage.upsert_product(product)
                report.imported += 1
            except Exception as exc:
                report.errors.append(f"Erro ao salvar {product.title}: {exc}")

        return report
