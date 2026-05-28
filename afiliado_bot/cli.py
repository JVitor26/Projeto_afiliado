from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .clients import AliExpressClient, AmazonClient, ManualProductClient, MercadoLivreClient, ShopeeClient
from .clients.manual import (
    enrich_product_from_url,
    manual_csv_headers,
    mercadolivre_public_info_from_text,
    product_from_promo_text,
)
from .config import AppConfig, BASE_DIR, load_config
from .models import Product
from .posters import DryRunPoster, TelegramPoster, WebhookPoster, WhatsAppPoster
from .redirect_server import serve_redirects
from .scheduler import run_forever
from .scoring import ProductRanker
from .services.mining import MiningService
from .services.publishing import PublishingService, build_offer_message
from .storage import Storage


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="afiliado-bot")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="cria ou atualiza o banco SQLite")

    ml_me_parser = subparsers.add_parser("mercadolivre-me", help="mostra o usuario Mercado Livre do token")
    ml_me_parser.add_argument("--token", help="access token temporario; se omitir usa MERCADOLIVRE_ACCESS_TOKEN")

    amazon_test_parser = subparsers.add_parser("amazon-creators-test", help="testa credenciais da Amazon Creators API")
    amazon_test_parser.add_argument("--keyword", default="fone bluetooth")
    amazon_test_parser.add_argument("--limit", type=int, default=3)

    ml_auth_parser = subparsers.add_parser("mercadolivre-auth-url", help="gera link para autorizar o app Mercado Livre")
    ml_auth_parser.add_argument("--redirect-uri", help="mesma URL de redirect cadastrada no app Mercado Livre")
    ml_auth_parser.add_argument("--state", help="valor opcional para validar o retorno OAuth")

    ml_token_parser = subparsers.add_parser("mercadolivre-token", help="troca o code OAuth por access token")
    ml_token_parser.add_argument("--code", required=True, help="codigo recebido na URL de retorno")
    ml_token_parser.add_argument("--redirect-uri", help="mesma URL usada no mercadolivre-auth-url")
    ml_token_parser.add_argument("--code-verifier", help="use somente se o app estiver com PKCE habilitado")

    ml_refresh_parser = subparsers.add_parser(
        "mercadolivre-refresh-token",
        help="renova o access token Mercado Livre usando MERCADOLIVRE_REFRESH_TOKEN",
    )
    ml_refresh_parser.add_argument(
        "--github-env",
        action="store_true",
        help="grava os tokens renovados no arquivo GITHUB_ENV sem imprimir os valores",
    )

    ml_public_parser = subparsers.add_parser(
        "mercadolivre-user-public",
        help="tenta descobrir vendedor por link publico de anuncio",
    )
    ml_public_parser.add_argument("--text", help="texto promocional ou link do Mercado Livre")
    ml_public_parser.add_argument("--file", help="arquivo .txt com o texto/link")
    ml_public_parser.add_argument("--link", help="link do anuncio")

    template_parser = subparsers.add_parser("manual-template", help="cria a planilha CSV de produtos manuais")
    template_parser.add_argument("--out", default=str(BASE_DIR / "data" / "manual_products.csv"))
    template_parser.add_argument("--force", action="store_true")

    manual_parser = subparsers.add_parser("manual-import", help="filtra e importa produtos preenchidos manualmente")
    manual_parser.add_argument("--limit", type=int, default=500)
    manual_parser.add_argument("--min-score", type=float)
    manual_parser.add_argument("--dry-run", action="store_true")
    manual_parser.add_argument("--review-out", default=str(BASE_DIR / "data" / "manual_products.reviewed.csv"))

    promo_parser = subparsers.add_parser(
        "promo-add",
        help="monta produto a partir de link ou texto promocional copiado",
    )
    promo_parser.add_argument("--text", help="texto promocional completo copiado do marketplace")
    promo_parser.add_argument("--file", help="arquivo .txt com o material promocional")
    promo_parser.add_argument("--link", help="link afiliado quando voce ainda nao tem o texto completo")
    promo_parser.add_argument("--category", default="")
    promo_parser.add_argument("--keywords", default="")
    promo_parser.add_argument("--min-score", type=float)
    promo_parser.add_argument("--no-enrich", action="store_true", help="nao tenta buscar dados pelo link")
    promo_parser.add_argument("--dry-run", action="store_true")

    send_parser = subparsers.add_parser(
        "promo-send",
        help="monta, salva, exporta a loja e envia a promocao para o Telegram",
    )
    send_parser.add_argument("--text", help="texto promocional completo copiado do marketplace")
    send_parser.add_argument("--file", help="arquivo .txt com o material promocional")
    send_parser.add_argument("--link", help="link afiliado quando voce ainda nao tem o texto completo")
    send_parser.add_argument("--category", default="")
    send_parser.add_argument("--keywords", default="")
    send_parser.add_argument("--min-score", type=float)
    send_parser.add_argument("--no-enrich", action="store_true", help="nao tenta buscar dados pelo link")
    send_parser.add_argument("--dry-run", action="store_true")
    send_parser.add_argument("--site-out", default=str(BASE_DIR / "site" / "products.js"))
    send_parser.add_argument("--site-limit", type=int, default=120)

    link_parser = subparsers.add_parser(
        "link-offer",
        help="cola um link e transforma automaticamente em oferta no site e telegram",
    )
    link_parser.add_argument("link", nargs="?", help="link do produto (ou cole via stdin)")
    link_parser.add_argument("--no-auto-publish", action="store_true", help="nao publica automaticamente")
    link_parser.add_argument("--site-out", default=str(BASE_DIR / "site" / "products.js"))
    link_parser.add_argument("--site-limit", type=int, default=120)

    mine_parser = subparsers.add_parser("mine", help="busca e ranqueia produtos")
    mine_parser.add_argument("--keyword", action="append", dest="keywords")
    mine_parser.add_argument("--limit-per-keyword", type=int)
    mine_parser.add_argument(
        "--allow-errors",
        action="store_true",
        help="continua com codigo 0 mesmo se alguma fonte bloquear ou falhar",
    )

    auto_ml_parser = subparsers.add_parser(
        "auto-mercadolivre",
        help="busca ofertas no Mercado Livre, atualiza a loja e publica no Telegram",
    )
    auto_ml_parser.add_argument("--keyword", action="append", dest="keywords")
    auto_ml_parser.add_argument("--limit-per-keyword", type=int)
    auto_ml_parser.add_argument("--publish-limit", type=int)
    auto_ml_parser.add_argument("--min-score", type=float)
    auto_ml_parser.add_argument("--site-out", default=str(BASE_DIR / "site" / "products.js"))
    auto_ml_parser.add_argument("--site-limit", type=int, default=120)
    auto_ml_parser.add_argument("--dry-run", action="store_true", help="nao envia ao Telegram; apenas mostra preview")
    auto_ml_parser.add_argument("--loop", action="store_true", help="repete a automacao a cada INTERVAL_MINUTES")

    auto_amazon_parser = subparsers.add_parser(
        "auto-amazon",
        help="busca ofertas na Amazon Creators API, atualiza a loja e publica no Telegram",
    )
    auto_amazon_parser.add_argument("--keyword", action="append", dest="keywords")
    auto_amazon_parser.add_argument("--limit-per-keyword", type=int)
    auto_amazon_parser.add_argument("--publish-limit", type=int)
    auto_amazon_parser.add_argument("--min-score", type=float)
    auto_amazon_parser.add_argument("--site-out", default=str(BASE_DIR / "site" / "products.js"))
    auto_amazon_parser.add_argument("--site-limit", type=int, default=120)
    auto_amazon_parser.add_argument("--dry-run", action="store_true", help="nao envia ao Telegram; apenas mostra preview")
    auto_amazon_parser.add_argument("--loop", action="store_true", help="repete a automacao a cada INTERVAL_MINUTES")

    publish_parser = subparsers.add_parser("publish", help="publica os melhores produtos")
    publish_parser.add_argument("--limit", type=int)
    publish_parser.add_argument("--min-score", type=float)
    publish_parser.add_argument("--dry-run", action="store_true")

    run_parser = subparsers.add_parser("run", help="executa mineracao e publicacao em loop")
    run_parser.add_argument("--limit-per-keyword", type=int)
    run_parser.add_argument("--publish-limit", type=int)

    serve_parser = subparsers.add_parser("serve", help="sobe servidor local de redirect/clicks")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8080)

    event_parser = subparsers.add_parser("record-event", help="registra clique ou venda manual")
    event_parser.add_argument("--product-id", type=int, required=True)
    event_parser.add_argument("--event", choices=["click", "sale"], required=True)
    event_parser.add_argument("--channel", default="manual")
    event_parser.add_argument("--value", type=float, default=1.0)

    seed_site_parser = subparsers.add_parser(
        "seed-site-products",
        help="importa produtos ja exportados em site/products.js para o banco",
    )
    seed_site_parser.add_argument("--path", default=str(BASE_DIR / "site" / "products.js"))
    seed_site_parser.add_argument("--limit", type=int, default=120)
    seed_site_parser.add_argument(
        "--only-if-empty",
        action="store_true",
        help="nao importa se o banco ja tiver produtos",
    )

    export_parser = subparsers.add_parser("export-site", help="exporta produtos para a loja estatica")
    export_parser.add_argument("--limit", type=int, default=120)
    export_parser.add_argument("--out", default=str(BASE_DIR / "site" / "products.js"))
    export_parser.add_argument(
        "--keep-existing-if-empty",
        action="store_true",
        help="mantem o products.js atual quando o banco nao tiver produtos exportaveis",
    )

    subparsers.add_parser("stats", help="mostra resumo do banco")

    args = parser.parse_args(argv)
    config = load_config()
    storage = Storage(config.database_path)
    storage.init_db()

    if args.command == "init-db":
        print(f"Banco pronto: {config.database_path}")
        return 0

    if args.command == "mercadolivre-me":
        token = args.token or config.mercadolivre_access_token
        if not token:
            print("MERCADOLIVRE_ACCESS_TOKEN nao configurado no .env.")
            print("Para usar /users/me, gere um access token OAuth e coloque em MERCADOLIVRE_ACCESS_TOKEN.")
            return 2
        try:
            profile = fetch_mercadolivre_me(token)
        except RuntimeError as exc:
            print(f"Erro Mercado Livre: {exc}")
            return 2
        print(f"ID: {profile.get('id')}")
        print(f"Nickname: {profile.get('nickname')}")
        print(f"Nome: {profile.get('first_name') or ''} {profile.get('last_name') or ''}".strip())
        print(f"Site: {profile.get('site_id')}")
        print(f"Permalink: {profile.get('permalink') or ''}")
        return 0

    if args.command == "amazon-creators-test":
        missing = amazon_creators_missing_config(config)
        if missing:
            print("Config Amazon Creators incompleta no .env:")
            for key in missing:
                print(f"- {key}")
            print("Preencha Credential ID, Credential Secret, Version e Partner Tag.")
            return 2
        client = AmazonClient(config)
        try:
            products = client.fetch(args.keyword, limit=args.limit)
        except RuntimeError as exc:
            print(f"Erro Amazon Creators API: {exc}")
            return 2
        print("Amazon Creators API: OK")
        print(f"Produtos retornados: {len(products)}")
        for product in products[: args.limit]:
            print(f"- {product.title} | {product.currency} {product.price:.2f}")
        return 0

    if args.command == "mercadolivre-auth-url":
        redirect_uri = args.redirect_uri or config.mercadolivre_redirect_uri
        if not config.mercadolivre_client_id:
            print("MERCADOLIVRE_CLIENT_ID nao configurado no .env.")
            return 2
        if not redirect_uri:
            print("MERCADOLIVRE_REDIRECT_URI nao configurado no .env.")
            return 2
        print(build_mercadolivre_auth_url(config.mercadolivre_client_id, redirect_uri, state=args.state or ""))
        return 0

    if args.command == "mercadolivre-token":
        redirect_uri = args.redirect_uri or config.mercadolivre_redirect_uri
        if not config.mercadolivre_client_id:
            print("MERCADOLIVRE_CLIENT_ID nao configurado no .env.")
            return 2
        if not config.mercadolivre_client_secret:
            print("MERCADOLIVRE_CLIENT_SECRET nao configurado no .env.")
            return 2
        if not redirect_uri:
            print("MERCADOLIVRE_REDIRECT_URI nao configurado no .env.")
            return 2
        try:
            token_payload = exchange_mercadolivre_code(
                config.mercadolivre_client_id,
                config.mercadolivre_client_secret,
                args.code,
                redirect_uri,
                code_verifier=args.code_verifier or "",
            )
        except RuntimeError as exc:
            print(f"Erro Mercado Livre: {exc}")
            return 2
        print("Cole estes valores no seu .env:")
        print(f"MERCADOLIVRE_ACCESS_TOKEN={token_payload.get('access_token') or ''}")
        if token_payload.get("refresh_token"):
            print(f"MERCADOLIVRE_REFRESH_TOKEN={token_payload.get('refresh_token')}")
        print(f"MERCADOLIVRE_USER_ID={token_payload.get('user_id') or ''}")
        print(f"Expira em segundos: {token_payload.get('expires_in') or ''}")
        return 0

    if args.command == "mercadolivre-refresh-token":
        if not config.mercadolivre_client_id:
            print("MERCADOLIVRE_CLIENT_ID nao configurado.")
            return 2
        if not config.mercadolivre_client_secret:
            print("MERCADOLIVRE_CLIENT_SECRET nao configurado.")
            return 2
        if not config.mercadolivre_refresh_token:
            print("MERCADOLIVRE_REFRESH_TOKEN nao configurado.")
            return 2
        try:
            token_payload = refresh_mercadolivre_token(
                config.mercadolivre_client_id,
                config.mercadolivre_client_secret,
                config.mercadolivre_refresh_token,
            )
        except RuntimeError as exc:
            print(f"Erro Mercado Livre: {exc}")
            return 2
        if args.github_env:
            github_env = os.getenv("GITHUB_ENV", "")
            if not github_env:
                print("GITHUB_ENV nao esta disponivel.")
                return 2
            _append_github_env(github_env, "MERCADOLIVRE_ACCESS_TOKEN", str(token_payload.get("access_token") or ""))
            if token_payload.get("refresh_token"):
                _append_github_env(github_env, "MERCADOLIVRE_REFRESH_TOKEN", str(token_payload["refresh_token"]))
            print("Tokens Mercado Livre renovados no GITHUB_ENV.")
            return 0
        print("Cole estes valores no seu .env e nos GitHub Actions secrets:")
        print(f"MERCADOLIVRE_ACCESS_TOKEN={token_payload.get('access_token') or ''}")
        if token_payload.get("refresh_token"):
            print(f"MERCADOLIVRE_REFRESH_TOKEN={token_payload.get('refresh_token')}")
        print(f"Expira em segundos: {token_payload.get('expires_in') or ''}")
        return 0

    if args.command == "mercadolivre-user-public":
        lookup_text = read_promo_input(args)
        if not lookup_text:
            print("Informe --text, --file, --link ou cole o link/texto via stdin.")
            return 2
        try:
            info = mercadolivre_public_info_from_text(lookup_text, config)
        except RuntimeError as exc:
            print(f"Erro Mercado Livre: {exc}")
            return 2
        if info.get("error"):
            print(f"Aviso: {info['error']}")
        print(f"Item ID: {info.get('item_id') or ''}")
        print(f"Seller ID: {info.get('seller_id') or ''}")
        print(f"Seller nome: {info.get('seller_name') or ''}")
        print(f"Produto: {info.get('title') or ''}")
        if info.get("price"):
            print(f"Preco: {info.get('currency') or 'BRL'} {float(info['price']):.2f}")
        print(f"Link resolvido: {info.get('resolved_url') or info.get('permalink') or ''}")
        if not info.get("seller_id"):
            print("Sem access token, alguns links publicos mostram o vendedor, mas nao expõem o seller_id.")
        return 0

    if args.command == "manual-template":
        out_path = Path(args.out)
        if not out_path.is_absolute():
            out_path = BASE_DIR / out_path
        created = create_manual_template(out_path, force=args.force)
        print(f"Planilha manual {'criada' if created else 'ja existe'}: {out_path}")
        return 0

    if args.command == "manual-import":
        min_score = config.min_score_to_publish if args.min_score is None else args.min_score
        report = import_manual_products(
            config,
            storage,
            limit=args.limit,
            min_score=min_score,
            dry_run=args.dry_run,
            review_out=Path(args.review_out),
        )
        print(f"Lidos: {report['total']}")
        imported_label = "Aprovados" if args.dry_run else "Importados"
        print(f"{imported_label}: {report['imported']}")
        print(f"Baixo score: {report['low_score']}")
        print(f"Rejeitados: {report['rejected']}")
        print(f"Revisao salva em: {report['review_out']}")
        return 0

    if args.command in {"promo-add", "promo-send"}:
        promo_text = read_promo_input(args)
        if not promo_text:
            print("Informe --text, --file, --link ou cole o material promocional via stdin.")
            return 2
        should_send = args.command == "promo-send"
        if args.min_score is not None:
            min_score = args.min_score
        elif should_send:
            min_score = 0.0
        else:
            min_score = config.min_score_to_publish
        result = add_promo_product(
            config,
            storage,
            promo_text,
            category=args.category,
            keywords=args.keywords,
            min_score=min_score,
            dry_run=args.dry_run,
            enrich=not args.no_enrich,
            require_details=should_send,
        )
        export_path = None
        publish_count = 0
        if should_send and result["status"] == "importado" and result["product"].id:
            export_path = Path(args.site_out)
            if not export_path.is_absolute():
                export_path = BASE_DIR / export_path
            export_store_products(storage, export_path, limit=args.site_limit)
            publish_count = publish_single_product(config, storage, result["product"], dry_run=False)

        print(f"Status: {result['status']}")
        print(f"Produto: {result['product'].title}")
        print(f"Preco: {result['product'].currency} {result['product'].price:.2f}")
        if result["product"].original_price:
            print(f"Preco original: {result['product'].currency} {result['product'].original_price:.2f}")
        print(f"Score: {result['product'].score:.2f}")
        if result["reason"]:
            print(f"Motivo: {result['reason']}")
        if result["product"].id:
            print(f"ID no banco: {result['product'].id}")
        if export_path:
            print(f"Site atualizado: {export_path}")
        if should_send:
            print(f"Telegram/publicacoes: {publish_count}")
        print("")
        print("Mensagem pronta:")
        print(result["message"])
        return 0 if result["status"] in {"importado", "aprovado_dry_run"} else 2

    if args.command == "link-offer":
        link = args.link or (sys.stdin.read().strip() if not sys.stdin.isatty() else "")
        if not link:
            print("Cole um link (Amazon, AliExpress, Shopee, Mercado Livre):")
            link = input().strip()
        if not link:
            print("Link nao fornecido.")
            return 2

        export_path = Path(args.site_out)
        if not export_path.is_absolute():
            export_path = BASE_DIR / export_path

        result = add_promo_product(
            config,
            storage,
            link,
            category="",
            keywords="",
            min_score=0.0,
            dry_run=False,
            enrich=True,
            require_details=False,
        )

        if result["status"] == "importado" and result["product"].id:
            export_store_products(storage, export_path, limit=args.site_limit)
            site_updated = export_path.exists()

            if not args.no_auto_publish:
                publish_count = publish_single_product(config, storage, result["product"], dry_run=False)
            else:
                publish_count = 0

            print("\n" + "="*60)
            print("[OK] OFERTA CRIADA COM SUCESSO!")
            print("="*60)
            print(f"Titulo:    {result['product'].title}")
            print(f"Preco:     {result['product'].currency} {result['product'].price:.2f}")
            if result["product"].original_price:
                discount = ((result['product'].original_price - result['product'].price) / result['product'].original_price * 100)
                print(f"Desconto:  {discount:.0f}%")
            print(f"Score:     {result['product'].score:.2f}")
            print(f"Fonte:     {result['product'].source.upper()}")
            print("")
            print(f"[+] Site atualizado: {export_path}")
            if site_updated:
                print(f"    Recarregue o navegador (F5) para ver a oferta")
            if not args.no_auto_publish:
                print(f"[+] Telegram publicacoes: {publish_count}")
            print("="*60)
        else:
            print("\n[ERRO] Problema ao processar link:")
            print(f"  Status: {result['status']}")
            print(f"  Motivo: {result['reason']}")
            if result['reason']:
                print(f"\n  Dica: {_get_hint_for_error(result['reason'])}")
            print("\n  Se o link for do AliExpress, tente colar o material promocional completo:")
            print("  echo \"texto promocional completo\" | python -m afiliado_bot link-offer")
            return 2

        return 0

    if args.command == "serve":
        serve_redirects(storage, args.host, args.port)
        return 0

    if args.command == "record-event":
        storage.record_event(args.product_id, args.event, channel=args.channel, value=args.value)
        print(f"Evento registrado: product_id={args.product_id} event={args.event}")
        return 0

    if args.command == "seed-site-products":
        site_products_path = Path(args.path)
        if not site_products_path.is_absolute():
            site_products_path = BASE_DIR / site_products_path
        imported = import_site_products(
            storage,
            site_products_path,
            limit=args.limit,
            only_if_empty=args.only_if_empty,
        )
        print(f"Produtos importados do site: {imported}")
        return 0

    if args.command == "stats":
        print(json.dumps(storage.stats(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "export-site":
        out_path = Path(args.out)
        if not out_path.is_absolute():
            out_path = BASE_DIR / out_path
        export_store_products(storage, out_path, limit=args.limit, keep_existing_if_empty=args.keep_existing_if_empty)
        print(f"Produtos exportados para: {out_path}")
        return 0

    mining = _build_mining(config, storage)

    if args.command == "mine":
        keywords = args.keywords or config.keywords
        report = mining.mine(
            keywords,
            limit_per_keyword=args.limit_per_keyword or config.mine_limit_per_keyword,
        )
        print(f"Importados: {report.imported}")
        print(f"Ignorados: {report.skipped}")
        if report.errors:
            print("Erros:")
            for error in report.errors:
                print(f"- {error}")
        return 0 if args.allow_errors or not report.errors else 2

    if args.command in {"auto-mercadolivre", "auto-amazon"}:
        if args.command == "auto-amazon":
            missing = amazon_creators_missing_config(config)
            if missing and not (config.amazon_product_feed_url or config.amazon_feed_path or config.amazon_creators_api_url):
                print("Config Amazon incompleta no .env:")
                for key in missing:
                    print(f"- {key}")
                print("Preencha os dados da Creators API ou configure AMAZON_FEED_PATH/AMAZON_PRODUCT_FEED_URL.")
                return 2

        exit_code = 0
        while True:
            provider = MercadoLivreClient(config) if args.command == "auto-mercadolivre" else AmazonClient(config)
            report = run_provider_auto(
                config,
                storage,
                provider=provider,
                keywords=args.keywords or config.keywords,
                limit_per_keyword=args.limit_per_keyword or config.mine_limit_per_keyword,
                publish_limit=args.publish_limit or config.publish_limit,
                min_score=config.min_score_to_publish if args.min_score is None else args.min_score,
                site_out=Path(args.site_out),
                site_limit=args.site_limit,
                dry_run=args.dry_run,
            )
            print(f"Minerados/importados: {report['imported']}")
            print(f"Ignorados: {report['skipped']}")
            if report["errors"]:
                print("Erros:")
                for error in report["errors"]:
                    print(f"- {error}")
                exit_code = 2
            print(f"Site atualizado: {report['site_out']}")
            print(f"Telegram/publicacoes: {report['sent']}")
            if not args.loop:
                return exit_code
            print(f"Aguardando {config.interval_minutes} minutos. Ctrl+C para parar.")
            time.sleep(max(config.interval_minutes, 1) * 60)

    if args.command == "publish":
        posters = _build_posters(config, force_dry_run=args.dry_run)
        publishing = PublishingService(config, storage, posters)
        sent = publishing.publish(
            limit=args.limit or config.publish_limit,
            dry_run=args.dry_run,
            min_score=args.min_score,
        )
        print(f"Publicacoes processadas: {sent}")
        return 0

    if args.command == "run":
        posters = _build_posters(config, force_dry_run=False)
        publishing = PublishingService(config, storage, posters)
        run_forever(
            config,
            mining,
            publishing,
            publish_limit=args.publish_limit,
            limit_per_keyword=args.limit_per_keyword,
        )
        return 0

    return 1


def _build_mining(config: AppConfig, storage: Storage) -> MiningService:
    enabled_sources = {source.strip().lower() for source in config.enabled_sources}
    providers = []
    manual = ManualProductClient(config)
    if "manual" in enabled_sources and manual.enabled:
        providers.append(manual)
    if "mercadolivre" in enabled_sources:
        providers.append(MercadoLivreClient(config))
    shopee = ShopeeClient(config)
    if "shopee" in enabled_sources and shopee.enabled:
        providers.append(shopee)
    amazon = AmazonClient(config)
    if "amazon" in enabled_sources and amazon.enabled:
        providers.append(amazon)
    aliexpress = AliExpressClient(config)
    if "aliexpress" in enabled_sources and aliexpress.enabled:
        providers.append(aliexpress)
    ranker = ProductRanker(config, storage.category_boosts())
    return MiningService(providers, storage, ranker)


def create_manual_template(out_path: Path, *, force: bool = False) -> bool:
    if out_path.exists() and not force:
        return False

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=manual_csv_headers())
        writer.writeheader()
        writer.writerow(
            {
                "approved": "no",
                "source": "amazon",
                "title": "Exemplo - troque por um produto real",
                "price": "99.90",
                "original_price": "149.90",
                "currency": "BRL",
                "url": "https://www.amazon.com.br/dp/EXEMPLO123",
                "affiliate_url": "",
                "image_url": "",
                "category": "fone bluetooth",
                "rating": "4.6",
                "sold_quantity": "100",
                "free_shipping": "sim",
                "commission_rate": "",
                "keywords": "fone bluetooth",
                "notes": "Linha de exemplo ignorada porque approved=no",
            }
        )
    return True


def build_mercadolivre_auth_url(client_id: str, redirect_uri: str, *, state: str = "") -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
    }
    if state:
        params["state"] = state
    return "https://auth.mercadolivre.com.br/authorization?" + urlencode(params)


def exchange_mercadolivre_code(
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    *,
    code_verifier: str = "",
) -> dict[str, object]:
    form = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
    }
    if code_verifier:
        form["code_verifier"] = code_verifier
    request = Request(
        "https://api.mercadolibre.com/oauth/token",
        data=urlencode(form).encode("utf-8"),
        headers={
            "accept": "application/json",
            "content-type": "application/x-www-form-urlencoded",
            "User-Agent": "afiliado-bot/0.1",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body[:300]}") from exc
    except URLError as exc:
        raise RuntimeError(f"erro de conexao: {exc.reason}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("resposta invalida da API")
    return payload


def refresh_mercadolivre_token(client_id: str, client_secret: str, refresh_token: str) -> dict[str, object]:
    form = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
    }
    request = Request(
        "https://api.mercadolibre.com/oauth/token",
        data=urlencode(form).encode("utf-8"),
        headers={
            "accept": "application/json",
            "content-type": "application/x-www-form-urlencoded",
            "User-Agent": "afiliado-bot/0.1",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body[:300]}") from exc
    except URLError as exc:
        raise RuntimeError(f"erro de conexao: {exc.reason}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("resposta invalida da API")
    return payload


def _append_github_env(github_env: str, key: str, value: str) -> None:
    with Path(github_env).open("a", encoding="utf-8") as file:
        file.write(f"{key}<<EOF\n{value}\nEOF\n")


def fetch_mercadolivre_me(token: str) -> dict[str, object]:
    request = Request(
        "https://api.mercadolibre.com/users/me",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "afiliado-bot/0.1",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body[:300]}") from exc
    except URLError as exc:
        raise RuntimeError(f"erro de conexao: {exc.reason}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("resposta invalida da API")
    return payload


def import_manual_products(
    config: AppConfig,
    storage: Storage,
    *,
    limit: int,
    min_score: float,
    dry_run: bool,
    review_out: Path,
) -> dict[str, object]:
    manual = ManualProductClient(config)
    ranker = ProductRanker(config, storage.category_boosts())
    products = manual.fetch_all(limit=limit)
    rows = []
    report = {
        "total": len(products),
        "imported": 0,
        "low_score": 0,
        "rejected": 0,
        "review_out": "",
    }

    for product in products:
        reason = ranker.reject_reason(product)
        score = 0.0
        status = "rejeitado"
        if reason:
            report["rejected"] += 1
        else:
            score = ranker.score(product)
            product.score = score
            if score >= min_score:
                status = "importado" if not dry_run else "aprovado_dry_run"
                if not dry_run:
                    product.id = storage.upsert_product(product)
                report["imported"] += 1
            else:
                status = "baixo_score"
                reason = f"score abaixo do minimo ({score:.2f} < {min_score:.2f})"
                report["low_score"] += 1

        rows.append(
            {
                "status": status,
                "reason": reason or "",
                "score": f"{score:.2f}",
                "source": product.source,
                "title": product.title,
                "price": f"{product.price:.2f}",
                "original_price": f"{product.original_price:.2f}" if product.original_price else "",
                "discount_percent": f"{product.discount_percent:.2f}",
                "category": product.category,
                "affiliate_url": product.affiliate_url,
                "notes": product.metadata.get("notes") or "",
            }
        )

    if not review_out.is_absolute():
        review_out = BASE_DIR / review_out
    review_out.parent.mkdir(parents=True, exist_ok=True)
    with review_out.open("w", encoding="utf-8-sig", newline="") as file:
        fieldnames = [
            "status",
            "reason",
            "score",
            "source",
            "title",
            "price",
            "original_price",
            "discount_percent",
            "category",
            "affiliate_url",
            "notes",
        ]
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    report["review_out"] = str(review_out)
    return report


def import_site_products(storage: Storage, products_path: Path, *, limit: int, only_if_empty: bool = False) -> int:
    if only_if_empty and storage.stats()["products"] > 0:
        return 0
    if not products_path.exists():
        return 0

    payload = _load_site_products(products_path)
    imported = 0
    for record in payload[: max(limit, 0)]:
        if not isinstance(record, dict):
            continue
        title = str(record.get("title") or "").strip()
        source = str(record.get("source") or "manual").strip().lower() or "manual"
        external_id = str(record.get("externalId") or record.get("external_id") or "").strip()
        affiliate_url = str(record.get("affiliateUrl") or record.get("affiliate_url") or "").strip()
        image_url = str(record.get("imageUrl") or record.get("image_url") or "").strip()
        price = _site_float(record.get("price"))
        if not title or not external_id or not affiliate_url:
            continue

        metadata = {
            key: record.get(key)
            for key in (
                "categoryLabel",
                "department",
                "commissionRate",
                "offerType",
                "periodEndTime",
                "sellerCompletedTransactions",
                "sellerPowerStatus",
                "sellerLevel",
                "officialStoreId",
                "officialStoreName",
            )
            if record.get(key) is not None
        }
        product = Product(
            source=source,
            external_id=external_id,
            title=title,
            price=price,
            original_price=_site_optional_float(record.get("originalPrice") or record.get("original_price")),
            currency=str(record.get("currency") or "BRL"),
            permalink=str(record.get("permalink") or affiliate_url),
            affiliate_url=affiliate_url,
            image_url=image_url,
            category=str(record.get("category") or record.get("categoryLabel") or "site"),
            score=_site_float(record.get("score")),
            rating=_site_optional_float(record.get("rating")),
            sold_quantity=_site_optional_int(record.get("soldQuantity") or record.get("sold_quantity")),
            free_shipping=bool(record.get("freeShipping") or record.get("free_shipping")),
            metadata={"raw_source": "site_products", **metadata},
        )
        storage.upsert_product(product)
        imported += 1
    return imported


def _load_site_products(products_path: Path) -> list[object]:
    content = products_path.read_text(encoding="utf-8-sig").strip()
    prefix = "window.LUMINA_PRODUCTS = "
    if content.startswith(prefix):
        content = content[len(prefix) :]
    if content.endswith(";"):
        content = content[:-1]
    payload = json.loads(content)
    return payload if isinstance(payload, list) else []


def _site_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _site_optional_float(value: object) -> float | None:
    parsed = _site_float(value)
    return parsed if parsed > 0 else None


def _site_optional_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def run_mercadolivre_auto(
    config: AppConfig,
    storage: Storage,
    *,
    keywords: list[str],
    limit_per_keyword: int,
    publish_limit: int,
    min_score: float,
    site_out: Path,
    site_limit: int,
    dry_run: bool,
) -> dict[str, object]:
    return run_provider_auto(
        config,
        storage,
        provider=MercadoLivreClient(config),
        keywords=keywords,
        limit_per_keyword=limit_per_keyword,
        publish_limit=publish_limit,
        min_score=min_score,
        site_out=site_out,
        site_limit=site_limit,
        dry_run=dry_run,
    )


def run_provider_auto(
    config: AppConfig,
    storage: Storage,
    *,
    provider: object,
    keywords: list[str],
    limit_per_keyword: int,
    publish_limit: int,
    min_score: float,
    site_out: Path,
    site_limit: int,
    dry_run: bool,
) -> dict[str, object]:
    providers = [provider]
    ranker = ProductRanker(config, storage.category_boosts())
    mining = MiningService(providers, storage, ranker)
    mining_report = mining.mine(keywords, limit_per_keyword=limit_per_keyword)

    if not site_out.is_absolute():
        site_out = BASE_DIR / site_out
    export_store_products(storage, site_out, limit=site_limit)

    posters = _build_posters(config, force_dry_run=dry_run)
    publishing = PublishingService(config, storage, posters)
    sent = publishing.publish(limit=publish_limit, dry_run=dry_run, min_score=min_score)

    return {
        "imported": mining_report.imported,
        "skipped": mining_report.skipped,
        "errors": mining_report.errors,
        "site_out": str(site_out),
        "sent": sent,
    }


def amazon_creators_missing_config(config: AppConfig) -> list[str]:
    required = {
        "AMAZON_CREATORS_CREDENTIAL_ID": config.amazon_creators_credential_id,
        "AMAZON_CREATORS_CREDENTIAL_SECRET": config.amazon_creators_credential_secret,
        "AMAZON_CREATORS_VERSION": config.amazon_creators_version,
        "AMAZON_PARTNER_TAG": config.amazon_partner_tag,
        "AMAZON_MARKETPLACE": config.amazon_marketplace,
    }
    return [key for key, value in required.items() if not str(value or "").strip()]


def read_promo_input(args: argparse.Namespace) -> str:
    if args.file:
        path = Path(args.file)
        if not path.is_absolute():
            path = BASE_DIR / path
        return path.read_text(encoding="utf-8").strip()
    if args.text:
        return args.text.strip()
    if args.link:
        return args.link.strip()
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    return ""


def add_promo_product(
    config: AppConfig,
    storage: Storage,
    promo_text: str,
    *,
    category: str,
    keywords: str,
    min_score: float,
    dry_run: bool,
    enrich: bool = True,
    require_details: bool = False,
) -> dict[str, object]:
    product = product_from_promo_text(
        promo_text,
        config,
        category=category,
        keywords=keywords,
    )
    if enrich:
        try:
            product = enrich_product_from_url(product, config)
        except RuntimeError as exc:
            product.metadata["enrichment_error"] = str(exc)

    ranker = ProductRanker(config, storage.category_boosts())
    reason = ranker.reject_reason(product)
    if not reason and require_details and _missing_required_details(product):
        reason = "nao consegui montar titulo e preco pelo link; cole o material completo ou verifique o link"
    status = "rejeitado"
    if reason:
        product.score = 0.0
    else:
        product.score = ranker.score(product)
        if product.score >= min_score:
            status = "aprovado_dry_run" if dry_run else "importado"
            if not dry_run:
                product.id = storage.upsert_product(product)
        else:
            status = "baixo_score"
            reason = f"score abaixo do minimo ({product.score:.2f} < {min_score:.2f})"

    return {
        "status": status,
        "reason": reason or "",
        "product": product,
        "message": build_offer_message(product, config.public_base_url),
    }


def _missing_required_details(product: object) -> bool:
    title = getattr(product, "title", "")
    price = float(getattr(product, "price", 0) or 0)
    source = getattr(product, "source", "")
    if title.startswith("Oferta "):
        return True
    if source == "amazon":
        return False
    return price <= 0


def publish_single_product(config: AppConfig, storage: Storage, product: object, *, dry_run: bool) -> int:
    posters = _build_posters(config, force_dry_run=dry_run)
    message = build_offer_message(product, config.public_base_url)
    sent = 0
    for poster in posters:
        results = poster.post(message, product)
        for result in results:
            status = "sent" if result.success and not dry_run else "preview" if dry_run else "failed"
            if getattr(product, "id", None) is not None:
                storage.add_post(product.id, result.channel, status, message, result.response)
            if result.success:
                sent += 1
    return sent


def _build_posters(config: AppConfig, *, force_dry_run: bool) -> list[object]:
    if force_dry_run:
        return [DryRunPoster()]

    posters: list[object] = []
    telegram = TelegramPoster(config)
    if telegram.enabled:
        posters.append(telegram)

    whatsapp = WhatsAppPoster(config)
    if whatsapp.enabled:
        posters.append(whatsapp)

    webhook = WebhookPoster(config)
    if webhook.enabled:
        posters.append(webhook)

    if not posters:
        posters.append(DryRunPoster())
    return posters


def export_store_products(storage: Storage, out_path: Path, *, limit: int, keep_existing_if_empty: bool = False) -> None:
    products = storage.list_products_for_store(limit=limit, require_image=True)
    payload = []
    for product in products:
        department, category_label = display_category_for_product(product)
        payload.append(
            {
                "id": product.id,
                "source": product.source,
                "externalId": product.external_id,
                "title": product.title,
                "price": product.price,
                "originalPrice": product.original_price,
                "currency": product.currency,
                "affiliateUrl": product.affiliate_url,
                "imageUrl": product.image_url,
                "category": product.category,
                "categoryLabel": category_label,
                "department": department,
                "score": product.score,
                "rating": product.rating,
                "soldQuantity": product.sold_quantity,
                "freeShipping": product.free_shipping,
                "discountPercent": product.discount_percent,
                "commissionRate": product.metadata.get("commission_rate"),
                "offerType": product.metadata.get("offer_type"),
                "periodEndTime": product.metadata.get("period_end_time"),
                "sellerCompletedTransactions": product.metadata.get("seller_completed_transactions"),
                "sellerPowerStatus": product.metadata.get("seller_power_seller_status"),
                "sellerLevel": product.metadata.get("seller_level_id"),
                "officialStoreId": product.metadata.get("official_store_id"),
                "officialStoreName": product.metadata.get("official_store_name"),
            }
        )

    if keep_existing_if_empty and not payload and out_path.exists():
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        "window.LUMINA_PRODUCTS = "
        + json.dumps(payload, ensure_ascii=False, indent=2)
        + ";\n",
        encoding="utf-8",
    )


def display_category_for_product(product: object) -> tuple[str, str]:
    title = str(getattr(product, "title", "") or "")
    raw_category = str(getattr(product, "category", "") or "")
    metadata = getattr(product, "metadata", {}) or {}
    keyword = str(metadata.get("keyword") or metadata.get("keywords") or "").strip()
    is_marketplace_code = raw_category.upper().startswith(("MLB", "MLA", "MLM", "MCO", "MLC", "MLU"))
    readable = raw_category or keyword or "geral"
    if is_marketplace_code and keyword:
        readable = keyword

    groups = [
        (
            "Tecnologia",
            (
                "celular",
                "smartphone",
                "iphone",
                "notebook",
                "monitor",
                "ssd",
                "fone",
                "headset",
                "bluetooth",
                "smartwatch",
                "tablet",
                "teclado",
                "mouse",
                "controle",
                "xbox",
                "playstation",
                "gamer",
                "caixa de som",
            ),
        ),
        (
            "Casa e cozinha",
            (
                "casa",
                "cozinha",
                "air fryer",
                "panela",
                "liquidificador",
                "cafeteira",
                "utensilio",
                "utensílio",
                "jogo de panelas",
                "organizador",
                "luminaria",
                "luminária",
            ),
        ),
        (
            "Eletrodomesticos",
            (
                "geladeira",
                "micro-ondas",
                "microondas",
                "maquina de lavar",
                "máquina de lavar",
                "aspirador",
                "ventilador",
                "climatizador",
                "fritadeira",
                "britania",
                "britânia",
            ),
        ),
        ("Cama, mesa e banho", ("cama", "mesa", "banho", "toalha", "jogo de cama", "lencol", "lençol")),
        ("Ferramentas", ("furadeira", "parafusadeira", "ferramenta", "chave", "broca")),
        ("Moda", ("tenis", "tênis", "mochila", "camiseta", "calca", "calça", "relogio", "relógio")),
        ("Beleza", ("beleza", "barbeador", "escova secadora", "secador", "perfume", "maquiagem")),
        ("Pets", ("pet", "cachorro", "gato", "racao", "ração")),
        ("Brinquedos", ("brinquedo", "lego", "boneca", "carrinho")),
        ("Automotivo", ("carro", "moto", "automotivo", "pneu", "bateria")),
    ]
    department = "Outras ofertas"
    category_text = readable.lower()
    for label, terms in groups:
        if any(term in category_text for term in terms):
            department = label
            break

    haystack = f"{title} {readable} {raw_category}".lower()
    for label, terms in groups:
        if department != "Outras ofertas":
            break
        if any(term in haystack for term in terms):
            department = label
            break

    return department, _clean_category_label(readable, title)


def _clean_category_label(value: str, title: str) -> str:
    text = value.strip()
    if not text or text.upper().startswith(("MLB", "MLA", "MLM", "MCO", "MLC", "MLU")):
        text = title
    text = text.replace("_", " ").replace("-", " ")
    text = " ".join(text.split())
    if not text:
        return "Geral"
    return text[:1].upper() + text[1:]


def _get_hint_for_error(reason: str) -> str:
    reason_lower = reason.lower()
    if "score" in reason_lower or "minimo" in reason_lower:
        return "Tente um link com melhor desconto, avaliação ou mais vendas."
    if "titulo" in reason_lower or "preco" in reason_lower:
        return "O link pode estar quebrado ou a página não carregou. Tente outro link."
    if "enrich" in reason_lower or "enrichment" in reason_lower:
        return "Não consegui extrair dados do link. Cole o link completo do marketplace."
    return "Verifique o link e tente novamente."
