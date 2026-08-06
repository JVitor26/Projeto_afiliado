import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from afiliado_bot.cli import (
    build_mercadolivre_auth_url,
    display_category_for_product,
    export_store_products,
    import_site_products,
    refresh_mercadolivre_token,
)
from afiliado_bot.clients.aliexpress import AliExpressClient
from afiliado_bot.clients.amazon import AmazonClient
from afiliado_bot.clients.manual import (
    ManualProductClient,
    _apply_amazon_html_metadata,
    _apply_mercadolivre_html_metadata,
    product_from_promo_text,
)
from afiliado_bot.clients.mercadolivre import _catalog_item_rank, _item_permalink
from afiliado_bot.clients.shopee import ShopeeClient
from afiliado_bot.config import AppConfig
from afiliado_bot.models import PostResult, Product
from afiliado_bot.posters.telegram import TelegramPoster
from afiliado_bot.posters.webhook import WebhookPoster
from afiliado_bot.posters.whatsapp import WhatsAppPoster
from afiliado_bot.scoring import ProductRanker
from afiliado_bot.services.publishing import PublishingService, build_offer_message
from afiliado_bot.storage import Storage


class FakeTelegramResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return b'{"ok":true}'


class CapturePoster:
    channel = "capture"

    def __init__(self):
        self.messages = []

    def post(self, message, product):
        self.messages.append((message, product))
        return [PostResult(channel=self.channel, success=True, response="ok")]


class CoreTests(unittest.TestCase):
    def test_mercadolivre_auth_url_uses_app_credentials(self):
        url = build_mercadolivre_auth_url(
            "123456",
            "https://example.com/callback",
            state="teste",
        )
        parsed = urlparse(url)
        query = parse_qs(parsed.query)

        self.assertEqual(parsed.netloc, "auth.mercadolivre.com.br")
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["client_id"], ["123456"])
        self.assertEqual(query["redirect_uri"], ["https://example.com/callback"])
        self.assertEqual(query["state"], ["teste"])

    def test_mercadolivre_refresh_token_uses_refresh_grant(self):
        captured = {}

        class FakeTokenResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return b'{"access_token":"novo-access","refresh_token":"novo-refresh","expires_in":21600}'

        def fake_urlopen(request, timeout):
            captured["data"] = parse_qs(request.data.decode("utf-8"))
            return FakeTokenResponse()

        with patch("afiliado_bot.commands.mercadolivre.urlopen", fake_urlopen):
            payload = refresh_mercadolivre_token("app-id", "secret", "refresh-atual")

        self.assertEqual(captured["data"]["grant_type"], ["refresh_token"])
        self.assertEqual(captured["data"]["client_id"], ["app-id"])
        self.assertEqual(captured["data"]["client_secret"], ["secret"])
        self.assertEqual(captured["data"]["refresh_token"], ["refresh-atual"])
        self.assertEqual(payload["access_token"], "novo-access")

    def test_display_category_prefers_readable_category_for_store(self):
        product = Product(
            source="mercadolivre",
            external_id="MLB1",
            title="Mochila para Notebook 15 polegadas",
            price=119,
            currency="BRL",
            permalink="https://produto.mercadolivre.com.br/MLB-1",
            affiliate_url="https://produto.mercadolivre.com.br/MLB-1",
            category="MLB3127",
            metadata={"keyword": "mochila"},
        )

        department, label = display_category_for_product(product)

        self.assertEqual(department, "Moda")
        self.assertEqual(label, "Mochila")

    def test_scoring_rewards_discount_and_shipping(self):
        product = Product(
            source="test",
            external_id="1",
            title="Produto em promocao",
            price=80,
            original_price=100,
            currency="BRL",
            permalink="https://example.com",
            affiliate_url="https://example.com",
            free_shipping=True,
            sold_quantity=100,
            rating=4.8,
        )
        score = ProductRanker(AppConfig()).score(product)
        self.assertGreater(score, 50)

    def test_scoring_rejects_products_without_image_by_default(self):
        product = Product(
            source="mercadolivre",
            external_id="MLB1",
            title="Produto sem imagem",
            price=80,
            currency="BRL",
            permalink="https://produto.mercadolivre.com.br/MLB-1",
            affiliate_url="https://produto.mercadolivre.com.br/MLB-1",
        )

        self.assertEqual(ProductRanker(AppConfig()).reject_reason(product), "missing product image")

    def test_scoring_rejects_known_low_sales(self):
        product = Product(
            source="mercadolivre",
            external_id="MLB1",
            title="Produto com uma venda",
            price=80,
            currency="BRL",
            permalink="https://produto.mercadolivre.com.br/MLB-1",
            affiliate_url="https://produto.mercadolivre.com.br/MLB-1",
            image_url="https://http2.mlstatic.com/produto.jpg",
            sold_quantity=1,
        )

        reason = ProductRanker(AppConfig(min_sold_quantity=5)).reject_reason(product)

        self.assertIn("sold quantity below minimum", reason)

    def test_storage_upsert_and_candidates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = Storage(Path(temp_dir) / "test.db")
            storage.init_db()
            product = Product(
                source="test",
                external_id="1",
                title="Produto teste",
                price=50,
                currency="BRL",
                permalink="https://example.com",
                affiliate_url="https://example.com",
                score=99,
            )
            product_id = storage.upsert_product(product)
            candidates = storage.list_candidates(limit=5, min_score=10)
            self.assertEqual(product_id, candidates[0].id)
            self.assertEqual(candidates[0].title, "Produto teste")

    def test_publish_reposts_old_product_when_no_unpublished_candidates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = Storage(Path(temp_dir) / "test.db")
            storage.init_db()
            product = Product(
                source="test",
                external_id="1",
                title="Produto antigo",
                price=50,
                currency="BRL",
                permalink="https://example.com",
                affiliate_url="https://example.com",
                score=99,
            )
            product_id = storage.upsert_product(product)
            storage.add_post(product_id, "telegram:@canal", "sent", "mensagem antiga", "ok")
            with storage.session() as conn:
                conn.execute("update posts set posted_at = '2000-01-01T00:00:00+00:00'")

            poster = CapturePoster()
            publishing = PublishingService(
                AppConfig(min_score_to_publish=25, repost_after_minutes=8),
                storage,
                [poster],
            )

            sent = publishing.publish(limit=1)

            self.assertEqual(sent, 1)
            self.assertEqual(len(poster.messages), 1)
            self.assertEqual(poster.messages[0][1].title, "Produto antigo")

    def test_export_store_products_skips_products_without_image(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = Storage(Path(temp_dir) / "test.db")
            storage.init_db()
            without_image = Product(
                source="test",
                external_id="1",
                title="Produto sem imagem",
                price=50,
                currency="BRL",
                permalink="https://example.com/1",
                affiliate_url="https://example.com/1",
                score=99,
            )
            with_image = Product(
                source="test",
                external_id="2",
                title="Produto com imagem",
                price=50,
                currency="BRL",
                permalink="https://example.com/2",
                affiliate_url="https://example.com/2",
                image_url="https://example.com/image.jpg",
                score=80,
            )
            storage.upsert_product(without_image)
            storage.upsert_product(with_image)
            out_path = Path(temp_dir) / "products.js"

            export_store_products(storage, out_path, limit=10)

            content = out_path.read_text(encoding="utf-8")
            self.assertIn("Produto com imagem", content)
            self.assertNotIn("Produto sem imagem", content)

    def test_export_store_products_can_preserve_existing_file_when_empty(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = Storage(Path(temp_dir) / "test.db")
            storage.init_db()
            out_path = Path(temp_dir) / "products.js"
            current_content = 'window.LUMINA_PRODUCTS = [{"title":"Atual"}];\n'
            out_path.write_text(current_content, encoding="utf-8")

            export_store_products(storage, out_path, limit=10, keep_existing_if_empty=True)

            self.assertEqual(out_path.read_text(encoding="utf-8"), current_content)

    def test_import_site_products_seeds_empty_database(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = Storage(Path(temp_dir) / "test.db")
            storage.init_db()
            site_products = Path(temp_dir) / "products.js"
            site_products.write_text(
                'window.LUMINA_PRODUCTS = [{"source":"mercadolivre",'
                '"externalId":"MLB123","title":"Oferta do site","price":99.9,'
                '"originalPrice":149.9,"currency":"BRL","affiliateUrl":"https://example.com/p",'
                '"imageUrl":"https://example.com/p.jpg","category":"fone bluetooth",'
                '"score":55,"freeShipping":true}];\n',
                encoding="utf-8",
            )

            imported = import_site_products(storage, site_products, limit=10, only_if_empty=True)
            candidates = storage.list_candidates(limit=5, min_score=25)

            self.assertEqual(imported, 1)
            self.assertEqual(candidates[0].title, "Oferta do site")
            self.assertEqual(candidates[0].image_url, "https://example.com/p.jpg")

    def test_shopee_offer_v2_mapping_uses_offer_link(self):
        payload = {
            "nodes": [
                {
                    "commissionRate": "0.0123",
                    "imageUrl": "https://example.com/image.jpg",
                    "offerLink": "https://shopee.com.br/afiliado",
                    "originalLink": "https://shopee.com.br/original",
                    "offerName": "Fone Bluetooth Premium",
                    "offerType": 2,
                    "categoryId": 100013,
                    "collectionId": 0,
                    "periodStartTime": 1779840000,
                    "periodEndTime": 1782432000,
                }
            ],
            "pageInfo": {"page": 1, "limit": 10, "hasNextPage": False},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "shopee.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            config = AppConfig(shopee_feed_path=path)
            products = ShopeeClient(config).fetch("fone bluetooth", limit=5)

        self.assertEqual(len(products), 1)
        self.assertEqual(products[0].title, "Fone Bluetooth Premium")
        self.assertEqual(products[0].affiliate_url, "https://shopee.com.br/afiliado")
        self.assertEqual(products[0].permalink, "https://shopee.com.br/original")
        self.assertEqual(products[0].price, 0)
        self.assertEqual(products[0].metadata["commission_rate"], 0.0123)

    def test_amazon_feed_mapping_applies_partner_template(self):
        payload = {
            "products": [
                {
                    "asin": "B0TEST123",
                    "title": "Fone Bluetooth Amazon",
                    "price": "129.90",
                    "original_price": "199.90",
                    "url": "https://www.amazon.com.br/dp/B0TEST123",
                    "image_url": "https://m.media-amazon.com/images/test.jpg",
                    "category": "fone bluetooth",
                    "rating": "4.7",
                    "review_count": "150",
                    "prime": "true",
                }
            ]
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "amazon.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            config = AppConfig(
                amazon_feed_path=path,
                amazon_partner_tag="loja-20",
                amazon_affiliate_template="{url}?tag={affiliate_id}",
            )
            products = AmazonClient(config).fetch("fone bluetooth", limit=5)

        self.assertEqual(len(products), 1)
        self.assertEqual(products[0].source, "amazon")
        self.assertEqual(products[0].affiliate_url, "https://www.amazon.com.br/dp/B0TEST123?tag=loja-20")
        self.assertEqual(products[0].discount_percent, 35.02)
        self.assertTrue(products[0].free_shipping)

    def test_amazon_creators_mapping_parses_lower_camel_response(self):
        item = {
            "asin": "B0CREATOR1",
            "detailPageURL": "https://www.amazon.com.br/dp/B0CREATOR1",
            "itemInfo": {"title": {"displayValue": "Headset Gamer Amazon"}},
            "images": {"primary": {"large": {"url": "https://m.media-amazon.com/images/creator.jpg"}}},
            "browseNodeInfo": {"browseNodes": [{"displayName": "Eletrônicos"}]},
            "offersV2": {
                "listings": [
                    {
                        "price": {"amount": 199.9, "currency": "BRL"},
                        "savingBasis": {"amount": 299.9},
                        "deliveryInfo": {"isFreeShippingEligible": True},
                    }
                ]
            },
        }
        config = AppConfig(amazon_partner_tag="loja-20", amazon_affiliate_template="{url}?tag={affiliate_id}")
        products = AmazonClient(config)._products_from_creators_items([item], "headset gamer")

        self.assertEqual(len(products), 1)
        self.assertEqual(products[0].external_id, "B0CREATOR1")
        self.assertEqual(products[0].title, "Headset Gamer Amazon")
        self.assertEqual(products[0].price, 199.9)
        self.assertEqual(products[0].original_price, 299.9)
        self.assertEqual(products[0].affiliate_url, "https://www.amazon.com.br/dp/B0CREATOR1?tag=loja-20")
        self.assertEqual(products[0].category, "Eletrônicos")
        self.assertTrue(products[0].free_shipping)
        self.assertEqual(products[0].metadata["raw_source"], "amazon_creators_api")

    def test_amazon_html_metadata_enriches_link_offer(self):
        html = """
        <html>
          <head>
            <meta content="Microfone USB Gamer RGB : Amazon.com.br: Instrumentos Musicais" property="og:title">
            <meta property="og:image" content="https://m.media-amazon.com/images/test.jpg">
          </head>
          <body>
            <span id="priceblock_dealprice">R$ 249,90</span>
            <span class="a-price a-text-price">
              <span class="a-offscreen">R$ 399,90</span>
            </span>
          </body>
        </html>
        """
        product = product_from_promo_text("https://amzn.to/teste", AppConfig())
        _apply_amazon_html_metadata(product, html)

        self.assertEqual(product.title, "Microfone USB Gamer RGB")
        self.assertEqual(product.price, 249.9)
        self.assertEqual(product.original_price, 399.9)
        self.assertEqual(product.image_url, "https://m.media-amazon.com/images/test.jpg")
        self.assertEqual(product.category, "microfone")

    def test_amazon_robot_check_does_not_replace_offer_title(self):
        html = "<title>Robot Check</title>"
        product = product_from_promo_text("https://amzn.to/teste", AppConfig())
        _apply_amazon_html_metadata(product, html)

        self.assertEqual(product.title, "Oferta Amazon")

    def test_aliexpress_feed_mapping_uses_promotion_link(self):
        payload = {
            "aliexpress_affiliate_product_query_response": {
                "resp_result": {
                    "result": {
                        "products": {
                            "product": [
                                {
                                    "product_id": "100500123",
                                    "product_title": "Smartwatch AliExpress Premium",
                                    "product_main_image_url": "https://ae01.alicdn.com/kf/test.jpg",
                                    "product_detail_url": "https://www.aliexpress.com/item/100500123.html",
                                    "promotion_link": "https://s.click.aliexpress.com/e/_promo",
                                    "target_sale_price": "R$ 89,90",
                                    "target_original_price": "R$ 129,90",
                                    "target_sale_price_currency": "BRL",
                                    "commission_rate": "7%",
                                    "evaluate_rate": "96%",
                                    "lastest_volume": "230",
                                    "first_level_category_name": "smartwatch",
                                }
                            ]
                        }
                    }
                }
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "aliexpress.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            config = AppConfig(aliexpress_feed_path=path, aliexpress_tracking_id="promo")
            products = AliExpressClient(config).fetch("smartwatch", limit=5)

        self.assertEqual(len(products), 1)
        self.assertEqual(products[0].source, "aliexpress")
        self.assertEqual(products[0].price, 89.9)
        self.assertEqual(products[0].affiliate_url, "https://s.click.aliexpress.com/e/_promo")
        self.assertEqual(products[0].metadata["commission_rate"], 0.07)
        self.assertEqual(products[0].rating, 4.8)

    def test_manual_feed_maps_marketplace_and_skips_rejected_rows(self):
        rows = "\n".join(
            [
                "approved,source,title,price,original_price,currency,url,affiliate_url,image_url,category,rating,sold_quantity,free_shipping,commission_rate,keywords,notes",
                "no,amazon,Produto recusado,10,20,BRL,https://www.amazon.com.br/dp/B0SKIPPED1,,,teste,,,,,,",
                "yes,amazon,Fone Bluetooth Manual,\"R$ 129,90\",\"R$ 199,90\",BRL,https://www.amazon.com.br/dp/B0MANUAL10,,,fone bluetooth,4.8,300,sim,,fone bluetooth,produto escolhido manualmente",
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "manual.csv"
            path.write_text(rows, encoding="utf-8")
            config = AppConfig(
                manual_products_path=path,
                amazon_partner_tag="loja-20",
                amazon_affiliate_template="{url}?tag={affiliate_id}",
            )
            products = ManualProductClient(config).fetch_all(limit=10)

        self.assertEqual(len(products), 1)
        self.assertEqual(products[0].source, "amazon")
        self.assertEqual(products[0].external_id, "B0MANUAL10")
        self.assertEqual(products[0].price, 129.9)
        self.assertEqual(products[0].affiliate_url, "https://www.amazon.com.br/dp/B0MANUAL10?tag=loja-20")
        self.assertTrue(products[0].free_shipping)

    def test_promo_text_builds_aliexpress_product(self):
        promo_text = """
        Principais recomendações de produtos à venda!
        Fifine microphone dinâmico usb/xlr com controle rgb/jack de fone de ouvido/mudo, microfone para gravação de jogos de pc
        streaming AmpliGame-AM8
        Agora preço: BRL 243.47 (Preço original: BRL 507.79, 52% desligado)
        Código disponível: FFIL001, BRL16.25 desligado, PST 2026-05-02 22:55:56 ~ 2026-06-30 23:59:59
        Clique e compre: https://s.click.aliexpress.com/e/_c4ODVCG1
        """
        product = product_from_promo_text(promo_text, AppConfig(), category="microfone")

        self.assertEqual(product.source, "aliexpress")
        self.assertIn("Fifine microphone", product.title)
        self.assertEqual(product.price, 243.47)
        self.assertEqual(product.original_price, 507.79)
        self.assertEqual(product.currency, "BRL")
        self.assertEqual(product.affiliate_url, "https://s.click.aliexpress.com/e/_c4ODVCG1")
        self.assertEqual(product.category, "microfone")
        self.assertEqual(product.metadata["coupon_code"], "FFIL001")
        self.assertEqual(product.metadata["coupon_discount"], 16.25)
        self.assertEqual(product.metadata["period_end"], "2026-06-30 23:59:59")

    def test_promo_text_builds_mercadolivre_link_offer(self):
        promo_text = """
        Cole este texto no buscador do Mercado Livre: G1Q50T-7TGA

        Ou acesse o link:
        https://meli.la/2v6vBf4
        """
        product = product_from_promo_text(promo_text, AppConfig())
        message = build_offer_message(product)

        self.assertEqual(product.source, "mercadolivre")
        self.assertEqual(product.title, "Oferta Mercado Livre")
        self.assertEqual(product.affiliate_url, "https://meli.la/2v6vBf4")
        self.assertEqual(product.metadata["search_code"], "G1Q50T-7TGA")
        self.assertIn("G1Q50T-7TGA", message)

    def test_offer_message_uses_compact_telegram_layout(self):
        product = Product(
            source="mercadolivre",
            external_id="MLB1",
            title="Samsung Galaxy S25 Ultra 5G 256GB",
            price=4749,
            original_price=10499,
            currency="BRL",
            permalink="https://produto.mercadolivre.com.br/MLB-1",
            affiliate_url="https://cutt.ly/RtMRtfOd",
            free_shipping=True,
            metadata={"installments": {"quantity": 10, "amount": 527.67}},
        )

        message = build_offer_message(product)

        self.assertIn("Samsung Galaxy S25 Ultra 5G 256GB", message)
        self.assertIn("R$ 4.749,00", message)
        self.assertIn("R$ 10.499,00", message)
        self.assertIn("FRETE GRÁTIS", message)
        self.assertIn("10x de R$ 527,67", message)
        self.assertIn("https://cutt.ly/RtMRtfOd", message)

    def test_mercadolivre_html_card_enriches_product(self):
        html = """
        <img class="poly-component__picture" src="https://http2.mlstatic.com/test.webp" alt="Carregador">
        <a href="https://www.mercadolivre.com.br/produto/p/MLB67421753?wid=MLB4571473797" class="poly-component__title">
        Carregador Celular 120w Rapido Compatível Xiaomi
        </a>
        <span class="poly-component__seller">Por Dona Magu</span>
        <s aria-label="Antes: 78 reais com 90 centavos"></s>
        <span aria-label="Agora: 24 reais com 70 centavos"></span>
        <span>68% OFF</span>
        <div>Frete grátis</div>
        """
        product = product_from_promo_text("https://meli.la/2v6vBf4", AppConfig())
        _apply_mercadolivre_html_metadata(product, html)

        self.assertEqual(product.external_id, "MLB4571473797")
        self.assertEqual(product.title, "Carregador Celular 120w Rapido Compatível Xiaomi")
        self.assertEqual(product.price, 24.7)
        self.assertEqual(product.original_price, 78.9)
        self.assertEqual(product.image_url, "https://http2.mlstatic.com/test.webp")
        self.assertEqual(product.metadata["seller_name"], "Dona Magu")
        self.assertTrue(product.free_shipping)

    def test_mercadolivre_catalog_helpers_rank_discounted_free_shipping_item(self):
        basic = {"item_id": "MLB123", "price": 30, "shipping": {"free_shipping": False}}
        better = {
            "item_id": "MLB456",
            "price": 35,
            "original_price": 43,
            "shipping": {"free_shipping": True},
        }

        self.assertGreater(_catalog_item_rank(better), _catalog_item_rank(basic))
        self.assertEqual(_item_permalink("MLB6483255322"), "https://produto.mercadolivre.com.br/MLB-6483255322")

    def test_telegram_posts_photo_when_product_has_image(self):
        calls = []

        def fake_urlopen(request, timeout):
            calls.append((request.full_url, parse_qs(request.data.decode("utf-8"))))
            return FakeTelegramResponse()

        product = Product(
            source="mercadolivre",
            external_id="MLB1",
            title="Oferta Mercado Livre",
            price=99,
            currency="BRL",
            permalink="https://produto.mercadolivre.com.br/MLB-1",
            affiliate_url="https://produto.mercadolivre.com.br/MLB-1",
            image_url="https://http2.mlstatic.com/produto.jpg",
        )
        poster = TelegramPoster(AppConfig(telegram_bot_token="token", telegram_chat_ids=["@canal"]))

        with patch("afiliado_bot.posters.telegram.urlopen", fake_urlopen):
            results = poster.post("<b>Oferta Mercado Livre</b>", product)

        self.assertTrue(results[0].success)
        self.assertEqual(len(calls), 1)
        self.assertIn("/sendPhoto", calls[0][0])
        self.assertEqual(calls[0][1]["photo"], ["https://http2.mlstatic.com/produto.jpg"])
        self.assertEqual(calls[0][1]["caption"], ["<b>Oferta Mercado Livre</b>"])

    def test_telegram_sends_photo_then_message_for_long_caption(self):
        calls = []

        def fake_urlopen(request, timeout):
            calls.append((request.full_url, parse_qs(request.data.decode("utf-8"))))
            return FakeTelegramResponse()

        product = Product(
            source="mercadolivre",
            external_id="MLB1",
            title="Oferta Mercado Livre",
            price=99,
            currency="BRL",
            permalink="https://produto.mercadolivre.com.br/MLB-1",
            affiliate_url="https://produto.mercadolivre.com.br/MLB-1",
            image_url="https://http2.mlstatic.com/produto.jpg",
        )
        poster = TelegramPoster(AppConfig(telegram_bot_token="token", telegram_chat_ids=["@canal"]))

        with patch("afiliado_bot.posters.telegram.urlopen", fake_urlopen):
            results = poster.post("x" * 1100, product)

        self.assertTrue(results[0].success)
        self.assertEqual(len(calls), 2)
        self.assertIn("/sendPhoto", calls[0][0])
        self.assertNotIn("caption", calls[0][1])
        self.assertIn("/sendMessage", calls[1][0])
        self.assertEqual(calls[1][1]["text"], ["x" * 1100])

    def test_whatsapp_posts_to_phone_number_via_graph_api(self):
        calls = []

        class FakeWhatsAppResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return b'{"messages":[{"id":"wamid.test"}]}'

        def fake_urlopen(request, timeout):
            calls.append((request.full_url, json.loads(request.data.decode("utf-8"))))
            return FakeWhatsAppResponse()

        product = Product(
            source="mercadolivre",
            external_id="MLB1",
            title="Oferta Mercado Livre",
            price=99,
            currency="BRL",
            permalink="https://produto.mercadolivre.com.br/MLB-1",
            affiliate_url="https://produto.mercadolivre.com.br/MLB-1",
        )
        poster = WhatsAppPoster(
            AppConfig(
                whatsapp_access_token="token",
                whatsapp_phone_number_id="123456",
                whatsapp_chat_ids=["+55 (65) 99999-9999"],
                whatsapp_graph_api_version="v25.0",
            )
        )

        with patch("afiliado_bot.posters.whatsapp.urlopen", fake_urlopen):
            results = poster.post("Oferta teste", product)

        self.assertTrue(results[0].success)
        self.assertEqual(calls[0][0], "https://graph.facebook.com/v25.0/123456/messages")
        self.assertEqual(calls[0][1]["messaging_product"], "whatsapp")
        self.assertEqual(calls[0][1]["recipient_type"], "individual")
        self.assertEqual(calls[0][1]["to"], "5565999999999")
        self.assertEqual(calls[0][1]["type"], "text")
        self.assertEqual(calls[0][1]["text"]["body"], "Oferta teste")

    def test_whatsapp_posts_image_with_offer_caption(self):
        calls = []

        class FakeWhatsAppResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return b'{"messages":[{"id":"wamid.test"}]}'

        def fake_urlopen(request, timeout):
            calls.append((request.full_url, json.loads(request.data.decode("utf-8"))))
            return FakeWhatsAppResponse()

        product = Product(
            source="mercadolivre",
            external_id="MLB1",
            title="Oferta Mercado Livre",
            price=99,
            currency="BRL",
            permalink="https://produto.mercadolivre.com.br/MLB-1",
            affiliate_url="https://produto.mercadolivre.com.br/MLB-1",
            image_url="https://http2.mlstatic.com/produto.jpg",
        )
        poster = WhatsAppPoster(
            AppConfig(
                whatsapp_access_token="token",
                whatsapp_phone_number_id="123456",
                whatsapp_chat_ids=["5565999999999"],
            )
        )

        with patch("afiliado_bot.posters.whatsapp.urlopen", fake_urlopen):
            results = poster.post("<b>Oferta Mercado Livre</b>\n\n➡️ <b>COMPRE PELO SITE:</b> https://exemplo", product)

        self.assertTrue(results[0].success)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]["type"], "image")
        self.assertEqual(calls[0][1]["image"]["link"], "https://http2.mlstatic.com/produto.jpg")
        self.assertIn("*Oferta Mercado Livre*", calls[0][1]["image"]["caption"])
        self.assertIn("*COMPRE PELO SITE:* https://exemplo", calls[0][1]["image"]["caption"])
        self.assertNotIn("<b>", calls[0][1]["image"]["caption"])

    def test_whatsapp_rejects_channel_link_recipient(self):
        product = Product(
            source="mercadolivre",
            external_id="MLB1",
            title="Oferta Mercado Livre",
            price=99,
            currency="BRL",
            permalink="https://produto.mercadolivre.com.br/MLB-1",
            affiliate_url="https://produto.mercadolivre.com.br/MLB-1",
        )
        poster = WhatsAppPoster(
            AppConfig(
                whatsapp_access_token="token",
                whatsapp_phone_number_id="123456",
                whatsapp_chat_ids=["https://whatsapp.com/channel/0029Vb6G99PK0IBmcPVy8s2w"],
            )
        )

        results = poster.post("Oferta teste", product)

        self.assertFalse(results[0].success)
        self.assertIn("Canal do WhatsApp", results[0].response)

    def test_webhook_payload_includes_whatsapp_channel_target(self):
        calls = []

        class FakeWebhookResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return b'{"ok":true}'

        def fake_urlopen(request, timeout):
            calls.append((request.full_url, json.loads(request.data.decode("utf-8"))))
            return FakeWebhookResponse()

        product = Product(
            source="mercadolivre",
            external_id="MLB1",
            title="Oferta Mercado Livre",
            price=99,
            original_price=149,
            currency="BRL",
            permalink="https://produto.mercadolivre.com.br/MLB-1",
            affiliate_url="https://produto.mercadolivre.com.br/MLB-1",
            image_url="https://http2.mlstatic.com/produto.jpg",
            category="fone bluetooth",
            score=88,
        )
        poster = WebhookPoster(
            AppConfig(
                webhook_urls=["https://example.com/webhook"],
                whatsapp_channel_url="https://whatsapp.com/channel/0029Vb6G99PK0IBmcPVy8s2w",
            )
        )

        with patch("afiliado_bot.posters.webhook.urlopen", fake_urlopen):
            results = poster.post("<b>Oferta Mercado Livre</b>", product)

        self.assertTrue(results[0].success)
        self.assertEqual(calls[0][0], "https://example.com/webhook")
        self.assertEqual(calls[0][1]["target"]["type"], "whatsapp_channel")
        self.assertEqual(calls[0][1]["target"]["url"], "https://whatsapp.com/channel/0029Vb6G99PK0IBmcPVy8s2w")
        self.assertEqual(calls[0][1]["whatsapp_channel"]["send_mode"], "image")
        self.assertEqual(calls[0][1]["whatsapp_channel"]["text"], "*Oferta Mercado Livre*")
        self.assertEqual(calls[0][1]["product"]["discount_percent"], product.discount_percent)


class RetryTests(unittest.TestCase):
    def test_retry_succeeds_after_transient_503(self):
        from urllib.error import HTTPError
        from afiliado_bot.clients.base import retry_http

        calls = []

        def flaky():
            calls.append(1)
            if len(calls) < 3:
                raise HTTPError("http://x", 503, "Service Unavailable", {}, None)
            return "ok"

        result = retry_http(flaky, attempts=3, base_delay=0)
        self.assertEqual(result, "ok")
        self.assertEqual(len(calls), 3)

    def test_retry_raises_on_non_retryable_404(self):
        from urllib.error import HTTPError
        from afiliado_bot.clients.base import retry_http

        def always_404():
            raise HTTPError("http://x", 404, "Not Found", {}, None)

        with self.assertRaises(HTTPError) as ctx:
            retry_http(always_404, attempts=3, base_delay=0)
        self.assertEqual(ctx.exception.code, 404)

    def test_retry_exhausts_all_attempts_on_persistent_503(self):
        from urllib.error import HTTPError
        from afiliado_bot.clients.base import retry_http

        calls = []

        def always_503():
            calls.append(1)
            raise HTTPError("http://x", 503, "Service Unavailable", {}, None)

        with self.assertRaises(HTTPError):
            retry_http(always_503, attempts=3, base_delay=0)
        self.assertEqual(len(calls), 3)


class AlertTests(unittest.TestCase):
    def test_publish_sends_alert_when_zero_products_sent(self):
        import tempfile
        from pathlib import Path
        from afiliado_bot.config import AppConfig
        from afiliado_bot.services.publishing import PublishingService
        from afiliado_bot.storage import Storage

        sent_alerts = []

        class MockPoster:
            channel = "telegram"

            def post(self, message, product):
                return []

        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "test.db")
            storage.init_db()

            config = AppConfig(
                telegram_bot_token="fake-token",
                telegram_chat_ids=["@canal"],
                min_score_to_publish=0.0,
                repost_after_minutes=0,
            )

            from unittest.mock import patch
            with patch("afiliado_bot.services.publishing._send_telegram_text") as mock_alert:
                service = PublishingService(config, storage, [MockPoster()])
                service.publish(limit=4, dry_run=False)
                self.assertTrue(mock_alert.called)

    def test_publish_does_not_alert_in_dry_run(self):
        import tempfile
        from pathlib import Path
        from afiliado_bot.config import AppConfig
        from afiliado_bot.services.publishing import PublishingService
        from afiliado_bot.storage import Storage

        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "test.db")
            storage.init_db()
            config = AppConfig(telegram_bot_token="fake-token", telegram_chat_ids=["@canal"])

            from unittest.mock import patch
            with patch("afiliado_bot.services.publishing._send_telegram_text") as mock_alert:
                service = PublishingService(config, storage, [])
                service.publish(limit=4, dry_run=True)
                mock_alert.assert_not_called()


class ClickMetricsTests(unittest.TestCase):
    def test_stats_by_source_counts_click_metadata(self):
        import tempfile
        from pathlib import Path
        from afiliado_bot.storage import Storage
        from afiliado_bot.models import Product

        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "test.db")
            storage.init_db()
            product = Product(
                source="mercadolivre",
                external_id="MLB1",
                title="Produto",
                price=99,
                currency="BRL",
                permalink="https://example.com",
                affiliate_url="https://example.com",
                category="fone bluetooth",
            )
            pid = storage.upsert_product(product)
            storage.record_event(pid, "click", channel="redirect", metadata={"source": "mercadolivre", "category": "fone bluetooth"})
            storage.record_event(pid, "click", channel="redirect", metadata={"source": "mercadolivre", "category": "fone bluetooth"})

            by_source = storage.stats_by_source()
            self.assertEqual(len(by_source), 1)
            self.assertEqual(by_source[0]["source"], "mercadolivre")
            self.assertEqual(by_source[0]["clicks"], 2)

            by_cat = storage.stats_by_category()
            self.assertEqual(by_cat[0]["category"], "fone bluetooth")
            self.assertEqual(by_cat[0]["clicks"], 2)


class StoreCommandsTests(unittest.TestCase):
    def test_display_category_from_new_module(self):
        from afiliado_bot.commands.store import display_category_for_product
        from afiliado_bot.models import Product

        product = Product(
            source="mercadolivre",
            external_id="MLB1",
            title="Notebook Dell",
            price=3000,
            currency="BRL",
            permalink="https://example.com",
            affiliate_url="https://example.com",
            category="notebook",
        )
        dept, label = display_category_for_product(product)
        self.assertEqual(dept, "Tecnologia")

    def test_generate_stats_js_creates_file(self):
        import tempfile
        from pathlib import Path
        from afiliado_bot.storage import Storage
        from afiliado_bot.commands.store import generate_stats_js

        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "test.db")
            storage.init_db()
            out = Path(tmp) / "stats.js"
            generate_stats_js(storage, out)
            content = out.read_text(encoding="utf-8")
            self.assertTrue(content.startswith("window.LUMINA_STATS = "))
            data = json.loads(content.removeprefix("window.LUMINA_STATS = ").removesuffix(";\n"))
            self.assertIn("products", data)
            self.assertIn("clicks_by_source", data)


BESTSELLERS_HTML = """
<div id="gridItemRoot">
<div id="B0BSVN58JW" class="p13n-sc-uncoverable-faceout">
  <a class="a-link-normal aok-block" href="/Pilha-Alcalina/dp/B0BSVN58JW/ref=zg_bs_g_electronics_d_sccl_1">
    <div class="a-section a-spacing-mini _cDEzb_noop_3Xbw5">
      <img alt="Pilha Alcalina AAA com 16 unidades Elgin Palito"
           src="https://images-na.ssl-images-amazon.com/images/I/517itypmYaL._AC_UL300_SR300,200_.jpg"
           data-a-dynamic-image="{&quot;https://images-na.ssl-images-amazon.com/images/I/517itypmYaL._AC_UL300_SR300,200_.jpg&quot;:[300,200],&quot;https://images-na.ssl-images-amazon.com/images/I/517itypmYaL._AC_UL900_SR900,600_.jpg&quot;:[900,600]}"/>
    </div>
  </a>
  <div class="_cDEzb_p13n-sc-css-line-clamp-3_g3dy1">Pilha Alcalina AAA com 16 unidades Elgin Palito</div>
  <div class="a-icon-row">
    <a aria-label="4,7 de 5 estrelas, 32.157 classifica&ccedil;&otilde;es" class="a-link-normal" href="/product-reviews/B0BSVN58JW">
      <i class="a-icon a-icon-star-small a-star-small-4-5"><span class="a-icon-alt">4,7 de 5 estrelas</span></i>
      <span aria-hidden="true" class="a-size-small">32.157</span>
    </a>
  </div>
  <span class="a-size-base a-color-price"><span class="_cDEzb_p13n-sc-price_3mJ9Z">R$ 17,89</span></span>
</div>
<div id="B0CVCLGV1W" class="p13n-sc-uncoverable-faceout">
  <img alt="Smartwatch Samsung Galaxy Fit3" src="https://images-na.ssl-images-amazon.com/images/I/51bjAlTBzZL._AC_UL300_.jpg"/>
  <div class="_cDEzb_p13n-sc-css-line-clamp-3_g3dy1">Smartwatch Samsung Galaxy Fit3 Display 1.6&quot; Grafite</div>
  <a aria-label="4,7 de 5 estrelas, 12.186 classifica&ccedil;&otilde;es" href="/product-reviews/B0CVCLGV1W"></a>
  <span class="_cDEzb_p13n-sc-price_3mJ9Z">R$ 1.218,90</span>
</div>
</div>
"""


class AmazonBestSellersTest(unittest.TestCase):
    def _config(self, **overrides):
        base = {"amazon_partner_tag": "67005-20", "amazon_marketplace": "www.amazon.com.br"}
        base.update(overrides)
        return AppConfig(**base)

    def _client(self, **overrides):
        from afiliado_bot.clients.amazon_bestsellers import AmazonBestSellersClient

        return AmazonBestSellersClient(self._config(**overrides))

    def test_parse_extracts_products_from_ranking(self):
        products = self._client()._parse(BESTSELLERS_HTML, "electronics", start_rank=1)

        self.assertEqual(len(products), 2)
        first = products[0]
        self.assertEqual(first.external_id, "B0BSVN58JW")
        self.assertEqual(first.title, "Pilha Alcalina AAA com 16 unidades Elgin Palito")
        self.assertAlmostEqual(first.price, 17.89)
        self.assertAlmostEqual(first.rating, 4.7)
        self.assertEqual(first.sold_quantity, 32157)
        self.assertEqual(first.category, "Eletrônicos")
        self.assertEqual(first.metadata["bestseller_rank"], 1)
        self.assertEqual(products[1].metadata["bestseller_rank"], 2)

    def test_parse_reads_brazilian_thousand_separator(self):
        products = self._client()._parse(BESTSELLERS_HTML, "electronics", start_rank=1)
        # "R$ 1.218,90" nao pode virar 1.21890 nem 121890
        self.assertAlmostEqual(products[1].price, 1218.90)

    def test_parse_picks_largest_image(self):
        products = self._client()._parse(BESTSELLERS_HTML, "electronics", start_rank=1)
        self.assertIn("_AC_UL900_SR900,600_", products[0].image_url)

    def test_parse_unescapes_html_entities_in_title(self):
        products = self._client()._parse(BESTSELLERS_HTML, "electronics", start_rank=1)
        self.assertIn('1.6"', products[1].title)

    def test_start_rank_offsets_second_page(self):
        products = self._client()._parse(BESTSELLERS_HTML, "electronics", start_rank=31)
        self.assertEqual(products[0].metadata["bestseller_rank"], 31)

    def test_affiliate_url_always_carries_partner_tag(self):
        products = self._client()._parse(BESTSELLERS_HTML, "electronics", start_rank=1)
        for product in products:
            self.assertIn("tag=67005-20", product.affiliate_url)
            self.assertTrue(product.affiliate_url.startswith("https://www.amazon.com.br/dp/"))

    def test_disabled_without_partner_tag(self):
        client = self._client(amazon_partner_tag="")
        self.assertFalse(client.enabled)

    def test_fetch_refuses_to_run_without_partner_tag(self):
        from afiliado_bot.clients.base import ProviderError

        client = self._client(amazon_partner_tag="")
        # Sem tag o link nao gera comissao: melhor falhar do que publicar de graca.
        with self.assertRaises(ProviderError):
            client.fetch("electronics", limit=5)

    def test_build_affiliate_url_rejects_empty_tag(self):
        from afiliado_bot.clients.amazon_bestsellers import build_affiliate_url

        with self.assertRaises(ValueError):
            build_affiliate_url("B0BSVN58JW", "")

    def test_pasted_link_gets_tag_even_without_template(self):
        from afiliado_bot.clients.manual import _apply_source_template

        # Cenario do GitHub Actions: AMAZON_AFFILIATE_TEMPLATE nao configurado.
        config = AppConfig(amazon_partner_tag="67005-20", amazon_affiliate_template="")
        link = _apply_source_template(
            "amazon",
            "https://www.amazon.com.br/dp/B0BSVN58JW/ref=zg_bs?psc=1",
            "B0BSVN58JW",
            config,
        )

        self.assertIn("tag=67005-20", link)

    def test_pasted_link_without_asin_falls_back_to_template(self):
        from afiliado_bot.clients.manual import _apply_source_template

        config = AppConfig(amazon_partner_tag="67005-20", amazon_affiliate_template="{url}&tag={affiliate_id}")
        link = _apply_source_template("amazon", "https://amzn.to/4c8dAfs?x=1", "", config)

        self.assertIn("tag=67005-20", link)

    def test_offer_message_shows_bestseller_rank(self):
        product = Product(
            source="amazon",
            external_id="B0BSVN58JW",
            title="Echo Dot",
            price=459.0,
            currency="BRL",
            permalink="https://www.amazon.com.br/dp/B0BSVN58JW",
            affiliate_url="https://www.amazon.com.br/dp/B0BSVN58JW?tag=67005-20",
            image_url="https://img.example/echo.jpg",
            rating=4.8,
            sold_quantity=92146,
            metadata={"bestseller_rank": 3, "bestseller_category": "Eletronicos"},
        )
        message = build_offer_message(product)

        self.assertIn("TOP #3 MAIS VENDIDOS", message)
        self.assertIn("#3 em Eletronicos", message)
        # Numero em formato brasileiro e rotulado como avaliacoes, nao vendas.
        self.assertIn("+92.146 avaliações", message)


class MineSerialTest(unittest.TestCase):
    class _Provider:
        name = "amazon"

        def __init__(self, products_by_keyword, fail_on=()):
            self.products_by_keyword = products_by_keyword
            self.fail_on = set(fail_on)
            self.calls = []

        def fetch(self, keyword, *, limit):
            self.calls.append(keyword)
            if keyword in self.fail_on:
                raise RuntimeError("boom")
            return self.products_by_keyword.get(keyword, [])

    def _product(self, external_id):
        return Product(
            source="amazon",
            external_id=external_id,
            title=f"Produto {external_id}",
            price=250.0,
            currency="BRL",
            permalink=f"https://www.amazon.com.br/dp/{external_id}",
            affiliate_url=f"https://www.amazon.com.br/dp/{external_id}?tag=67005-20",
            image_url="https://img.example/p.jpg",
            rating=4.6,
            sold_quantity=1200,
        )

    def _run(self, provider, keywords):
        from afiliado_bot.services.mining import MiningService

        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "test.db")
            storage.init_db()
            config = AppConfig(min_price=0.0, min_discount_percent=0.0, min_sold_quantity=0)
            service = MiningService([provider], storage, ProductRanker(config))
            return service.mine_serial(keywords, limit_per_keyword=5, delay_seconds=0)

    def test_visits_every_category_in_order(self):
        provider = self._Provider({"electronics": [self._product("A1")], "kitchen": [self._product("B2")]})
        report = self._run(provider, ["electronics", "kitchen"])

        self.assertEqual(provider.calls, ["electronics", "kitchen"])
        self.assertEqual(report.imported, 2)

    def test_one_failing_category_does_not_stop_the_others(self):
        provider = self._Provider({"kitchen": [self._product("B2")]}, fail_on=["electronics"])
        report = self._run(provider, ["electronics", "kitchen"])

        self.assertEqual(provider.calls, ["electronics", "kitchen"])
        self.assertEqual(report.imported, 1)
        self.assertEqual(len(report.errors), 1)


class WatermarkTest(unittest.TestCase):
    def test_soften_rounds_corners_and_lowers_opacity(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow nao instalado")

        from afiliado_bot.image_utils import _soften

        logo = Image.new("RGBA", (120, 120), (255, 80, 30, 255))
        softened = _soften(logo, opacity=0.6, corner_radius=0.25)

        # Canto vira transparente...
        self.assertLess(softened.getpixel((0, 0))[3], 20)
        # ...e o miolo fica translucido, nao opaco.
        self.assertAlmostEqual(softened.getpixel((60, 60))[3], 153, delta=6)


if __name__ == "__main__":
    unittest.main()
