import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from afiliado_bot.cli import build_mercadolivre_auth_url, display_category_for_product, export_store_products
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
from afiliado_bot.models import Product
from afiliado_bot.posters.telegram import TelegramPoster
from afiliado_bot.posters.webhook import WebhookPoster
from afiliado_bot.posters.whatsapp import WhatsAppPoster
from afiliado_bot.scoring import ProductRanker
from afiliado_bot.services.publishing import build_offer_message
from afiliado_bot.storage import Storage


class FakeTelegramResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return b'{"ok":true}'


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
        self.assertIn("Código Mercado Livre: <b>G1Q50T-7TGA</b>", message)

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

        self.assertIn("<b>Samsung Galaxy S25 Ultra 5G 256GB</b> | De <s>R$ 10.499,00</s> Por <b>R$ 4.749,00</b> (no Pix)", message)
        self.assertIn("🔥 Oferta com 55% OFF no produto!", message)
        self.assertIn("💸 Frete Grátis (Consultar CEP)", message)
        self.assertIn("✅ Ou 10x de R$ 527,67 no cartão", message)
        self.assertIn("➡️ <b>COMPRE PELO SITE:</b> https://cutt.ly/RtMRtfOd", message)

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


if __name__ == "__main__":
    unittest.main()
