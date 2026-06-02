from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .storage import Storage


def serve_redirects(storage: Storage, host: str, port: int) -> None:
    handler = _handler_factory(storage)
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Redirect server running at http://{host}:{port}")
    server.serve_forever()


def _handler_factory(storage: Storage) -> type[BaseHTTPRequestHandler]:
    class RedirectHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")
                return

            if not parsed.path.startswith("/r/"):
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"not found")
                return

            raw_id = parsed.path.removeprefix("/r/").strip("/")
            try:
                product_id = int(raw_id)
            except ValueError:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"invalid product id")
                return

            product = storage.get_product(product_id)
            if not product:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"product not found")
                return

            storage.record_event(
                product_id,
                "click",
                channel="redirect",
                metadata={
                    "source": product.source,
                    "category": product.category,
                    "referrer": self.headers.get("Referer", ""),
                    "user_agent": self.headers.get("User-Agent", "")[:120],
                },
            )
            self.send_response(302)
            self.send_header("Location", product.affiliate_url)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    return RedirectHandler
