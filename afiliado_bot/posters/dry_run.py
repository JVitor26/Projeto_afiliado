from __future__ import annotations

from afiliado_bot.models import PostResult, Product


class DryRunPoster:
    channel = "dry-run"

    def post(self, message: str, product: Product) -> list[PostResult]:
        print("\n--- POST PREVIEW ---")
        print(message)
        print(f"Produto #{product.id or '-'} | score={product.score} | {product.affiliate_url}")
        print("--- END PREVIEW ---\n")
        return [PostResult(channel=self.channel, success=True, response="preview")]
