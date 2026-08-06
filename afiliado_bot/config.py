from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_ALIEXPRESS_FIELDS = (
    "product_id,product_title,product_main_image_url,product_detail_url,"
    "promotion_link,target_sale_price,target_original_price,target_sale_price_currency,"
    "discount,commission_rate,evaluate_rate,lastest_volume,first_level_category_name"
)
DEFAULT_KEYWORDS = (
    # ── Televisores e áudio (alta procura, ticket alto) ─────
    "smart tv 4k,smart tv samsung,smart tv lg,televisor 4k,tv 50 polegadas,"
    "tv 55 polegadas,tv 65 polegadas,soundbar,home theater,caixa de som jbl,"
    "caixa de som bluetooth potente,subwoofer,receiver amplificador,projetor,"
    # ── Celulares e acessórios ──────────────────────────────
    "smartphone samsung,iphone,celular xiaomi,celular motorola,celular realme,"
    "fone bluetooth,headset sem fio,airpods,smartwatch,tablet samsung,"
    # ── Informática e games ─────────────────────────────────
    "notebook samsung,notebook dell,notebook lenovo,notebook acer,monitor gamer,"
    "ssd nvme,placa de video,memoria ram,processador,roteador wifi 6,"
    "playstation 5,ps5,xbox series,nintendo switch,controle gamer,"
    "cadeira gamer,mesa gamer,headset gamer,teclado mecanico,mouse gamer,"
    # ── Eletrodomésticos de alto valor ──────────────────────
    "geladeira inverse,geladeira frost free,adega climatizador,"
    "maquina de lavar 11kg,maquina de lavar 12kg,lava e seca,"
    "fogao 5 bocas,fogao cooktop,forno eletrico,lava-loucas,"
    "ar condicionado split,ar condicionado portatil,"
    "aspirador robot,aspirador sem fio,robo aspirador,"
    # ── Cozinha premium ─────────────────────────────────────
    "air fryer,fritadeira sem oleo,cafeteira nespresso,cafeteira expresso,"
    "liquidificador,batedeira planetaria,processador de alimentos,panela de pressao,"
    "panela eletrica de pressao,churrasqueira eletrica,jogo de panelas,"
    # ── Moveis e casa ───────────────────────────────────────
    "sofa,poltrona,mesa de jantar,mesa escritorio,escrivaninha,"
    "guarda-roupa,armario,cama box,colchao,rack tv,estante,"
    "luminaria teto,pendente,abajur,cortina blackout,"
    # ── Ferramentas e construção ────────────────────────────
    "furadeira parafusadeira,kit ferramentas,lavadora de alta pressao,"
    "esmerilhadeira,compressor de ar,caixa de ferramentas,"
    # ── Automotivo de alto interesse ────────────────────────
    "camera veicular,som automotivo,central multimidia,gps veicular,"
    "pneu,bateria automotiva,suporte celular carro,"
    # ── Saúde e bem-estar ───────────────────────────────────
    "massageador eletrico,medidor de pressao arterial,oximetro,"
    "bicicleta ergometrica,esteira eletrica,eliptico,"
    "suplemento proteina,whey protein,creatina,"
    # ── Moda e acessórios de valor ──────────────────────────
    "relogio masculino,relogio feminino,oculos de sol,bolsa feminina,"
    "tenis esportivo,tenis corrida,calca jeans,jaqueta,"
    # ── Beleza e cuidados ───────────────────────────────────
    "perfume importado,perfume feminino,perfume masculino,"
    "secador de cabelo profissional,chapinha,prancha,modelador,"
    "maquiagem kit,base liquida,paleta de sombras,"
    # ── Pet ─────────────────────────────────────────────────
    "racao premium cachorro,racao premium gato,cama pet,arranhador gato,"
    # ── Bebê ────────────────────────────────────────────────
    "carrinho bebe,cadeirinha bebe carro,berco,kit higiene bebe"
)
# Slugs das listas "Mais Vendidos" da Amazon BR (amazon.com.br/gp/bestsellers/<slug>).
# Ordem importa: as primeiras sao as de maior ticket/comissao.
DEFAULT_BESTSELLERS_CATEGORIES = (
    "electronics,computers,videogames,appliances,kitchen,"
    "home,hpc,beauty,toys,sports,automotive,office-products"
)
DEFAULT_DENY_KEYWORDS = (
    # ── Produto usado / não-novo (nunca publicar) ───────────
    "usado,quebrado,defeito,recondicionado,replica,imitacao,falso,"
    "seminovo,semi novo,semi-novo,recuperado,reembalado,caixa aberta,"
    "produto de vitrine,avariado,revenda,para revenda,produto de revenda,atacado,"
    # ── Acessórios genéricos / baixo valor que poluem buscas ─
    "capinha,capa para celular,capa protetora para celular,"
    "pelicula de vidro,película de vidro,pingente,chaveiro,berloque,"
    "bijuteria,brinco,colar folheado,adesivo de parede,miniatura colecionavel,"
    "kit 10 unidades,kit com 10 unidades"
)


def load_dotenv(path: Path | None = None) -> None:
    env_path = path or Path(os.getenv("APP_ENV_FILE", BASE_DIR / ".env"))
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not os.environ.get(key):
            os.environ[key] = value


def _csv(name: str, default: str = "") -> list[str]:
    value = os.getenv(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "sim", "on"}


@dataclass(frozen=True)
class AppConfig:
    database_path: Path = BASE_DIR / "data" / "affiliate.db"
    public_base_url: str = ""

    keywords: list[str] = field(default_factory=list)
    deny_keywords: list[str] = field(default_factory=list)
    min_price: float = 0.0
    max_price: float = 0.0
    min_discount_percent: float = 0.0
    min_score_to_publish: float = 15.0
    require_product_image: bool = True
    min_sold_quantity: int = 5
    min_seller_transactions: int = 25

    manual_products_path: Path = BASE_DIR / "data" / "manual_products.csv"
    manual_affiliate_template: str = ""
    manual_affiliate_id: str = ""

    mercadolivre_site_id: str = "MLB"
    mercadolivre_client_id: str = ""
    mercadolivre_client_secret: str = ""
    mercadolivre_redirect_uri: str = ""
    mercadolivre_access_token: str = ""
    mercadolivre_refresh_token: str = ""
    mercadolivre_affiliate_template: str = ""
    mercadolivre_affiliate_id: str = ""
    mercadolivre_min_discount: int = 10

    shopee_feed_path: Path | None = None
    shopee_product_feed_url: str = ""
    shopee_authorization_header: str = ""
    shopee_affiliate_template: str = ""
    shopee_affiliate_id: str = ""
    shopee_sort_type: int = 1
    shopee_start_page: int = 1
    shopee_app_id: str = ""
    shopee_app_secret: str = ""
    shopee_api_url: str = "https://open-api.affiliate.shopee.com.br/graphql"
    shopee_list_type: int = 0

    aliexpress_mode: str = "auto"
    aliexpress_feed_path: Path | None = None
    aliexpress_product_feed_url: str = ""
    aliexpress_authorization_header: str = ""
    aliexpress_api_url: str = "https://api-sg.aliexpress.com/sync"
    aliexpress_app_key: str = ""
    aliexpress_app_secret: str = ""
    aliexpress_tracking_id: str = ""
    aliexpress_affiliate_template: str = ""
    aliexpress_sign_method: str = "sha256"
    aliexpress_target_currency: str = "BRL"
    aliexpress_target_language: str = "PT"
    aliexpress_ship_to_country: str = "BR"
    aliexpress_sort: str = ""
    aliexpress_start_page: int = 1
    aliexpress_fields: str = DEFAULT_ALIEXPRESS_FIELDS

    amazon_mode: str = "auto"
    amazon_feed_path: Path | None = None
    amazon_product_feed_url: str = ""
    amazon_authorization_header: str = ""
    amazon_creators_api_url: str = ""
    amazon_creators_credential_id: str = ""
    amazon_creators_credential_secret: str = ""
    amazon_creators_version: str = "3.1"
    amazon_creators_token_url: str = ""
    amazon_access_key: str = ""
    amazon_secret_key: str = ""
    amazon_partner_tag: str = ""
    amazon_partner_type: str = "Associates"
    amazon_host: str = "webservices.amazon.com.br"
    amazon_region: str = "us-east-1"
    amazon_marketplace: str = "www.amazon.com.br"
    amazon_search_index: str = "All"
    amazon_affiliate_template: str = ""

    amazon_bestsellers_categories: list[str] = field(default_factory=list)
    amazon_bestsellers_limit: int = 8
    amazon_bestsellers_pages: int = 1
    amazon_bestsellers_attempts: int = 4
    amazon_bestsellers_delay: float = 4.0

    telegram_bot_token: str = ""
    telegram_chat_ids: list[str] = field(default_factory=list)
    telegram_tech_bot_token: str = ""
    telegram_tech_chat_ids: list[str] = field(default_factory=list)
    telegram_parse_mode: str = "HTML"
    telegram_disable_web_page_preview: bool = False

    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_chat_ids: list[str] = field(default_factory=list)
    whatsapp_graph_api_version: str = "v25.0"
    whatsapp_channel_url: str = ""

    # WhatsApp nao-oficial para grupos (Evolution API ou Green API)
    whatsapp_group_api_url: str = ""
    whatsapp_group_api_key: str = ""
    whatsapp_group_instance: str = ""
    whatsapp_group_api_type: str = "evolution"
    whatsapp_group_ids: list[str] = field(default_factory=list)

    webhook_urls: list[str] = field(default_factory=list)

    mine_limit_per_keyword: int = 20
    mining_parallel_keywords: int = 4
    mining_parallel_providers: int = 5
    mining_timeout_seconds: int = 300
    publish_limit: int = 4
    interval_minutes: int = 8
    repost_after_minutes: int = 15
    enabled_sources: list[str] = field(default_factory=list)


def load_config() -> AppConfig:
    load_dotenv()
    shopee_feed = os.getenv("SHOPEE_FEED_PATH", "").strip()
    shopee_feed_path = Path(shopee_feed) if shopee_feed else None
    if shopee_feed_path and not shopee_feed_path.is_absolute():
        shopee_feed_path = BASE_DIR / shopee_feed_path

    aliexpress_feed = os.getenv("ALIEXPRESS_FEED_PATH", "").strip()
    aliexpress_feed_path = Path(aliexpress_feed) if aliexpress_feed else None
    if aliexpress_feed_path and not aliexpress_feed_path.is_absolute():
        aliexpress_feed_path = BASE_DIR / aliexpress_feed_path

    amazon_feed = os.getenv("AMAZON_FEED_PATH", "").strip()
    amazon_feed_path = Path(amazon_feed) if amazon_feed else None
    if amazon_feed_path and not amazon_feed_path.is_absolute():
        amazon_feed_path = BASE_DIR / amazon_feed_path

    manual_products = Path(os.getenv("MANUAL_PRODUCTS_PATH", BASE_DIR / "data" / "manual_products.csv"))
    if not manual_products.is_absolute():
        manual_products = BASE_DIR / manual_products

    database_path = Path(os.getenv("DATABASE_PATH", BASE_DIR / "data" / "affiliate.db"))
    if not database_path.is_absolute():
        database_path = BASE_DIR / database_path

    return AppConfig(
        database_path=database_path,
        public_base_url=os.getenv("PUBLIC_BASE_URL", "").rstrip("/"),
        keywords=_csv(
            "KEYWORDS",
            DEFAULT_KEYWORDS,
        ),
        deny_keywords=_csv("DENY_KEYWORDS", DEFAULT_DENY_KEYWORDS),
        min_price=_float("MIN_PRICE", 80.0),
        max_price=_float("MAX_PRICE", 0.0),
        min_discount_percent=_float("MIN_DISCOUNT_PERCENT", 15.0),
        min_score_to_publish=_float("MIN_SCORE_TO_PUBLISH", 35.0),
        require_product_image=_bool("REQUIRE_PRODUCT_IMAGE", True),
        min_sold_quantity=_int("MIN_SOLD_QUANTITY", 20),
        min_seller_transactions=_int("MIN_SELLER_TRANSACTIONS", 50),
        manual_products_path=manual_products,
        manual_affiliate_template=os.getenv("MANUAL_AFFILIATE_TEMPLATE", ""),
        manual_affiliate_id=os.getenv("MANUAL_AFFILIATE_ID", ""),
        mercadolivre_site_id=os.getenv("MERCADOLIVRE_SITE_ID", "MLB"),
        mercadolivre_client_id=os.getenv("MERCADOLIVRE_CLIENT_ID", ""),
        mercadolivre_client_secret=os.getenv("MERCADOLIVRE_CLIENT_SECRET", ""),
        mercadolivre_redirect_uri=os.getenv("MERCADOLIVRE_REDIRECT_URI", ""),
        mercadolivre_access_token=os.getenv("MERCADOLIVRE_ACCESS_TOKEN", ""),
        mercadolivre_refresh_token=os.getenv("MERCADOLIVRE_REFRESH_TOKEN", ""),
        mercadolivre_affiliate_template=os.getenv("MERCADOLIVRE_AFFILIATE_TEMPLATE", ""),

        mercadolivre_affiliate_id=os.getenv("MERCADOLIVRE_AFFILIATE_ID", ""),
        mercadolivre_min_discount=_int("MERCADOLIVRE_MIN_DISCOUNT", 10),
        shopee_feed_path=shopee_feed_path,
        shopee_product_feed_url=os.getenv("SHOPEE_PRODUCT_FEED_URL", ""),
        shopee_authorization_header=os.getenv("SHOPEE_AUTHORIZATION_HEADER", ""),
        shopee_affiliate_template=os.getenv("SHOPEE_AFFILIATE_TEMPLATE", ""),
        shopee_affiliate_id=os.getenv("SHOPEE_AFFILIATE_ID", ""),
        shopee_sort_type=_int("SHOPEE_SORT_TYPE", 1),
        shopee_start_page=_int("SHOPEE_START_PAGE", 1),
        shopee_app_id=os.getenv("SHOPEE_APP_ID", "").strip(),
        shopee_app_secret=os.getenv("SHOPEE_APP_SECRET", "").strip(),
        shopee_api_url=os.getenv("SHOPEE_API_URL", "https://open-api.affiliate.shopee.com.br/graphql").strip(),
        shopee_list_type=_int("SHOPEE_LIST_TYPE", 0),
        aliexpress_mode=os.getenv("ALIEXPRESS_MODE", "auto").lower(),
        aliexpress_feed_path=aliexpress_feed_path,
        aliexpress_product_feed_url=os.getenv("ALIEXPRESS_PRODUCT_FEED_URL", ""),
        aliexpress_authorization_header=os.getenv("ALIEXPRESS_AUTHORIZATION_HEADER", ""),
        aliexpress_api_url=os.getenv("ALIEXPRESS_API_URL", "https://api-sg.aliexpress.com/sync"),
        aliexpress_app_key=os.getenv("ALIEXPRESS_APP_KEY", ""),
        aliexpress_app_secret=os.getenv("ALIEXPRESS_APP_SECRET", ""),
        aliexpress_tracking_id=os.getenv("ALIEXPRESS_TRACKING_ID", ""),
        aliexpress_affiliate_template=os.getenv("ALIEXPRESS_AFFILIATE_TEMPLATE", ""),
        aliexpress_sign_method=os.getenv("ALIEXPRESS_SIGN_METHOD", "sha256").lower(),
        aliexpress_target_currency=os.getenv("ALIEXPRESS_TARGET_CURRENCY", "BRL"),
        aliexpress_target_language=os.getenv("ALIEXPRESS_TARGET_LANGUAGE", "PT"),
        aliexpress_ship_to_country=os.getenv("ALIEXPRESS_SHIP_TO_COUNTRY", "BR"),
        aliexpress_sort=os.getenv("ALIEXPRESS_SORT", ""),
        aliexpress_start_page=_int("ALIEXPRESS_START_PAGE", 1),
        aliexpress_fields=os.getenv("ALIEXPRESS_FIELDS", DEFAULT_ALIEXPRESS_FIELDS) or DEFAULT_ALIEXPRESS_FIELDS,
        amazon_mode=os.getenv("AMAZON_MODE", "auto").lower(),
        amazon_feed_path=amazon_feed_path,
        amazon_product_feed_url=os.getenv("AMAZON_PRODUCT_FEED_URL", ""),
        amazon_authorization_header=os.getenv("AMAZON_AUTHORIZATION_HEADER", ""),
        amazon_creators_api_url=os.getenv("AMAZON_CREATORS_API_URL", ""),
        amazon_creators_credential_id=os.getenv("AMAZON_CREATORS_CREDENTIAL_ID", ""),
        amazon_creators_credential_secret=os.getenv("AMAZON_CREATORS_CREDENTIAL_SECRET", ""),
        amazon_creators_version=os.getenv("AMAZON_CREATORS_VERSION", "3.1"),
        amazon_creators_token_url=os.getenv("AMAZON_CREATORS_TOKEN_URL", ""),
        amazon_access_key=os.getenv("AMAZON_ACCESS_KEY", ""),
        amazon_secret_key=os.getenv("AMAZON_SECRET_KEY", ""),
        amazon_partner_tag=os.getenv("AMAZON_PARTNER_TAG", ""),
        amazon_partner_type=os.getenv("AMAZON_PARTNER_TYPE", "Associates"),
        amazon_host=os.getenv("AMAZON_HOST", "webservices.amazon.com.br"),
        amazon_region=os.getenv("AMAZON_REGION", "us-east-1"),
        amazon_marketplace=os.getenv("AMAZON_MARKETPLACE", "www.amazon.com.br"),
        amazon_search_index=os.getenv("AMAZON_SEARCH_INDEX", "All"),
        amazon_affiliate_template=os.getenv("AMAZON_AFFILIATE_TEMPLATE", ""),
        amazon_bestsellers_categories=_csv("AMAZON_BESTSELLERS_CATEGORIES", DEFAULT_BESTSELLERS_CATEGORIES),
        amazon_bestsellers_limit=_int("AMAZON_BESTSELLERS_LIMIT", 8),
        amazon_bestsellers_pages=_int("AMAZON_BESTSELLERS_PAGES", 1),
        amazon_bestsellers_attempts=_int("AMAZON_BESTSELLERS_ATTEMPTS", 4),
        amazon_bestsellers_delay=_float("AMAZON_BESTSELLERS_DELAY", 4.0),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_chat_ids=_csv("TELEGRAM_CHAT_IDS"),
        telegram_tech_bot_token=os.getenv("TELEGRAM_TECH_BOT_TOKEN", "").strip(),
        telegram_tech_chat_ids=_csv("TELEGRAM_TECH_CHAT_IDS"),
        telegram_parse_mode=os.getenv("TELEGRAM_PARSE_MODE", "HTML"),
        telegram_disable_web_page_preview=_bool("TELEGRAM_DISABLE_WEB_PAGE_PREVIEW", False),
        whatsapp_access_token=os.getenv("WHATSAPP_ACCESS_TOKEN", ""),
        whatsapp_phone_number_id=os.getenv("WHATSAPP_PHONE_NUMBER_ID", ""),
        whatsapp_chat_ids=_csv("WHATSAPP_CHAT_IDS"),
        whatsapp_graph_api_version=os.getenv("WHATSAPP_GRAPH_API_VERSION", "v25.0"),
        whatsapp_channel_url=os.getenv("WHATSAPP_CHANNEL_URL", ""),
        whatsapp_group_api_url=os.getenv("WHATSAPP_GROUP_API_URL", ""),
        whatsapp_group_api_key=os.getenv("WHATSAPP_GROUP_API_KEY", ""),
        whatsapp_group_instance=os.getenv("WHATSAPP_GROUP_INSTANCE", ""),
        whatsapp_group_api_type=os.getenv("WHATSAPP_GROUP_API_TYPE", "evolution"),
        whatsapp_group_ids=_csv("WHATSAPP_GROUP_IDS"),
        webhook_urls=_csv("SOCIAL_WEBHOOK_URLS"),
        mine_limit_per_keyword=_int("MINE_LIMIT_PER_KEYWORD", 20),
        mining_parallel_keywords=_int("MINING_PARALLEL_KEYWORDS", 4),
        mining_parallel_providers=_int("MINING_PARALLEL_PROVIDERS", 5),
        mining_timeout_seconds=_int("MINING_TIMEOUT_SECONDS", 300),
        publish_limit=_int("PUBLISH_LIMIT", 4),
        interval_minutes=_int("INTERVAL_MINUTES", 8),
        repost_after_minutes=_int("REPOST_AFTER_MINUTES", 15),
        enabled_sources=_csv("ENABLED_SOURCES", "manual,mercadolivre,shopee,amazon,aliexpress"),
    )
