# Projeto Afiliado Mercado Livre, Shopee, Amazon e AliExpress

Sistema inicial para minerar produtos, ranquear ofertas, gerar mensagens com link de afiliado e publicar automaticamente no Telegram ou em outros canais via webhook.

Importante: "vendas automaticas" aqui significa divulgacao automatica de ofertas com link afiliado. A compra continua acontecendo dentro do Mercado Livre, Shopee, Amazon ou AliExpress, seguindo as regras oficiais de cada programa.

## O que ja vem pronto

- Mineracao por palavras-chave no Mercado Livre usando API HTTP.
- Conector Shopee por feed JSON/CSV oficial/exportado ou endpoint proprio.
- Conector Amazon por Creators API/endpoint proprio/feed e PA-API legada.
- Conector AliExpress por API oficial de afiliados, feed JSON/CSV ou endpoint proprio.
- Fluxo manual por CSV para filtrar produtos enquanto as APIs nao estao liberadas.
- Ranking por desconto, preco, frete gratis, vendas, avaliacao e desempenho historico.
- Banco SQLite com deduplicacao de produtos publicados.
- Publicacao no Telegram Bot API.
- Webhook para n8n, Make, Zapier, Meta Graph API proxy ou outras redes.
- Servidor de redirect `/r/{id}` para medir cliques antes de redirecionar ao link afiliado.
- Loop de automacao para trazer produtos novos diariamente ou em intervalos menores.

## Configuracao rapida

1. Copie `config.example.env` para `.env`.
2. Edite `.env` com suas credenciais e nichos.
3. Rode:

```powershell
python -m afiliado_bot init-db
python -m afiliado_bot mine --limit-per-keyword 10
python -m afiliado_bot publish --limit 3 --dry-run
```

Quando o preview estiver bom, configure `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_IDS`, depois rode:

```powershell
python -m afiliado_bot publish --limit 3
```

## Bot manual sem API

Enquanto Amazon, AliExpress ou Shopee nao liberarem API/feeds, use a planilha manual:

```powershell
python -m afiliado_bot manual-template
```

Edite `data/manual_products.csv` e preencha uma linha por produto. Use `approved=yes` para produtos reais que voce quer avaliar. A linha de exemplo vem com `approved=no` e e ignorada.

Campos principais:

- `source`: `amazon`, `aliexpress`, `shopee`, `mercadolivre` ou `manual`.
- `title`: nome do produto.
- `price` e `original_price`: preco atual e preco anterior para calcular desconto.
- `url`: link do produto ou link afiliado.
- `affiliate_url`: opcional; se preencher, o bot usa esse link direto.
- `category`, `rating`, `sold_quantity`, `free_shipping`, `commission_rate` e `keywords`: ajudam o bot a ranquear.

Para filtrar e importar somente os produtos que passarem no score minimo:

```powershell
python -m afiliado_bot manual-import --dry-run
python -m afiliado_bot manual-import
python -m afiliado_bot publish --limit 3 --dry-run
```

O comando gera `data/manual_products.reviewed.csv` com `status`, `reason` e `score`, mostrando exatamente o que foi aprovado, rejeitado ou ficou com score baixo.

Tambem da para colar direto o material promocional do AliExpress e deixar o bot montar o produto:

```powershell
@"
Principais recomendações de produtos à venda!
Fifine microphone dinâmico usb/xlr com controle rgb/jack de fone de ouvido/mudo, microfone para gravação de jogos de pc streaming AmpliGame-AM8
Agora preço: BRL 243.47 (Preço original: BRL 507.79, 52% desligado)
Código disponível: FFIL001, BRL16.25 desligado, PST 2026-05-02 22:55:56 ~ 2026-06-30 23:59:59
Clique e compre: https://s.click.aliexpress.com/e/_c4ODVCG1
"@ | python -m afiliado_bot promo-add --category "microfone" --dry-run
```

Quando o preview estiver correto, rode sem `--dry-run`:

```powershell
@"
cole aqui o material promocional completo
"@ | python -m afiliado_bot promo-add --category "microfone"
python -m afiliado_bot publish --limit 1 --dry-run
```

Se voce colar apenas um link com `python -m afiliado_bot promo-add --link "https://..."`, o bot tenta completar os dados quando o marketplace permitir. Para Amazon (`amzn.to` ou `amazon.com.br`) e Mercado Livre (`meli.la`), ele abre o link, busca titulo, preco e imagem, e usa "conferir no marketplace" quando algum dado estiver oculto. Para preencher cupom e desconto automaticamente, cole o bloco completo de `Promo Material`.

Para enviar uma oferta escolhida manualmente da Amazon, cole o link curto ou link do produto no `promo-send`. Esse comando salva, atualiza a loja e publica no Telegram quando houver titulo valido; o score fica apenas como informacao, a menos que voce passe `--min-score`.

```powershell
@"
https://amzn.to/4wX5gIC
"@ | python -m afiliado_bot promo-send
```

Para o formato do Mercado Livre, cole o bloco inteiro. O bot tenta abrir o link `meli.la`, identificar o item, preencher titulo, preco, imagem e categoria, salvar no banco, atualizar a loja e publicar no Telegram:

```powershell
@"
Cole este texto no buscador do Mercado Livre: G1Q50T-7TGA

Ou acesse o link:
https://meli.la/2v6vBf4
"@ | python -m afiliado_bot promo-send
```

Nesse fluxo, quando encontra um ID `MLB...`, o bot usa o endpoint publico `https://api.mercadolibre.com/items?ids=MLB...` para completar os dados do produto. Quando o link cai numa pagina social/recomendacoes, ele le o primeiro card da propria pagina como fallback.

Para testar sem salvar nem enviar:

```powershell
@"
Cole este texto no buscador do Mercado Livre: G1Q50T-7TGA

Ou acesse o link:
https://meli.la/2v6vBf4
"@ | python -m afiliado_bot promo-send --dry-run
```

Para rodar em loop:

```powershell
python -m afiliado_bot run
```

Para automatizar só Mercado Livre sem colar links manualmente, use:

```powershell
python -m afiliado_bot auto-mercadolivre --dry-run
```

Quando o preview estiver correto, rode sem `--dry-run` para atualizar `site/products.js` e publicar no Telegram:

```powershell
python -m afiliado_bot auto-mercadolivre
```

O comando usa as `KEYWORDS` do `.env`. A configuracao padrao foca em tecnologia, eletrodomesticos, ferramentas, produtos de casa, utensilios de cozinha e automotivo. Para buscar nichos especificos nessa execucao:

```powershell
python -m afiliado_bot auto-mercadolivre --keyword "fone bluetooth" --keyword "smartwatch"
```

Por padrao, o bot publica 1 produto a cada 8 minutos (`PUBLISH_LIMIT=1`, `INTERVAL_MINUTES=8` e `REPOST_AFTER_MINUTES=8`). Quando nao houver produto novo, ele republica ofertas antigas em rotacao respeitando esse intervalo. Para deixar repetindo automaticamente:

```powershell
python -m afiliado_bot auto-mercadolivre --loop
```

Se minerar produtos mas nao publicar nenhum, reduza o score minimo:

```powershell
python -m afiliado_bot auto-mercadolivre --min-score 0 --dry-run
```

Para evitar ofertas fracas, o bot exige imagem por padrao e rejeita produtos com venda baixa quando o marketplace informa esse dado. Ajuste `REQUIRE_PRODUCT_IMAGE`, `MIN_SOLD_QUANTITY` e `MIN_SELLER_TRANSACTIONS` no `.env` se quiser ser mais ou menos rigoroso.

A loja em `site/index.html` separa os produtos por departamento, mostra uma sidebar com categorias detalhadas e oferece filtros por marketplace, preco minimo, preco maximo e frete gratis. Depois de qualquer mineracao, o arquivo `site/products.js` e atualizado para refletir as categorias.

## Shopee (Affiliate Open API)

No painel de afiliados voce gera link clicando em **Obter link** produto por
produto, e o modal devolve algo como `https://s.shopee.com.br/19NjoyPDx`. A Open
API faz esse mesmo trabalho de uma vez: o campo `offerLink` de cada produto ja
vem nesse formato de afiliado, entao **nao e preciso configurar template** — o
link sai com sua atribuicao garantida.

Pegue as credenciais em **affiliate.shopee.com.br > menu lateral > Abrir API** e
coloque no `.env`:

```env
ENABLED_SOURCES=manual,mercadolivre,shopee,amazon,aliexpress
SHOPEE_APP_ID=seu_app_id
SHOPEE_APP_SECRET=seu_app_secret
# listType 0 = todas as ofertas
# sortType 2 = maior comissao | 3 = mais vendidos
SHOPEE_LIST_TYPE=0
SHOPEE_SORT_TYPE=2
```

Teste sem publicar nada:

```powershell
python -m afiliado_bot shopee-test --keyword "air fryer"
```

Se aparecer **erro 10035**, a conta ainda nao tem acesso liberado a Open API —
solicite a liberacao na propria pagina "Abrir API". A autenticacao e assinada:
`SHA256(appId + timestamp + payload + appSecret)`, enviada no cabecalho
`Authorization: SHA256 Credential=..., Timestamp=..., Signature=...`.

O conector antigo por feed/proxy (`SHOPEE_PRODUCT_FEED_URL`, `SHOPEE_FEED_PATH`)
continua funcionando como alternativa; a Open API tem prioridade quando o App ID
e o Secret estiverem preenchidos.

## Vigiar a saude das lojas

Uma loja pode parar de trazer produtos sem ninguem perceber: `mine --allow-errors`
continua com codigo 0 para nao derrubar o ciclo por causa de uma fonte, entao o
workflow segue verde enquanto a fonte esta morta. Foi o que aconteceu com o
Mercado Livre, que ficou meses parado em silencio.

```powershell
python -m afiliado_bot check-sources --hours 24 --dry-run   # so mostra
python -m afiliado_bot check-sources --hours 24             # avisa no Telegram
```

Sao vigiadas apenas as fontes que estao em `ENABLED_SOURCES` **e** tem
credencial configurada — alertar sobre loja que nunca foi configurada vira
ruido, e alerta que vira ruido deixa de ser lido. Roda sozinho no workflow.

### Refresh token do Mercado Livre (importante)

O refresh token do Mercado Livre e de **uso unico**: cada renovacao devolve um
novo e invalida o anterior. O access token dura 6 horas. O workflow renova a
cada execucao, mas para que a renovacao sobreviva ao proximo run e preciso
gravar o token novo de volta no secret — senao a execucao seguinte reapresenta
um token ja consumido e o Mercado Livre passa a responder 401 permanentemente.

Para isso, crie um token de acesso pessoal com permissao de **escrita em
secrets** neste repositorio e cadastre como secret `GH_SECRETS_TOKEN`. Sem ele o
workflow apenas emite um aviso e o Mercado Livre volta a quebrar em algumas
horas.

## Telegram

Crie um bot no BotFather, coloque o token em `TELEGRAM_BOT_TOKEN` e informe um ou mais chats/canais em `TELEGRAM_CHAT_IDS`, separados por virgula.

Exemplo:

```env
TELEGRAM_BOT_TOKEN=123456:ABC
TELEGRAM_CHAT_IDS=@PromoLinkBrasil99
```

O bot precisa estar no canal/grupo com permissao para publicar. Para canal publico, use o usuario do canal com `@`, como `@PromoLinkBrasil99`.

## Mercado Livre

O conector usa a busca de itens do Mercado Livre para o site `MLB`. O `ID do aplicativo` e a `Chave secreta` nao sao o access token; eles servem para gerar o token OAuth da sua conta.

Coloque as credenciais do app no `.env`:

```env
MERCADOLIVRE_CLIENT_ID=seu_id_do_aplicativo
MERCADOLIVRE_CLIENT_SECRET=sua_chave_secreta
MERCADOLIVRE_REDIRECT_URI=https://a-mesma-url-cadastrada-no-app
MERCADOLIVRE_ACCESS_TOKEN=
MERCADOLIVRE_REFRESH_TOKEN=
```

Depois gere o link de autorizacao:

```powershell
python -m afiliado_bot mercadolivre-auth-url
```

Abra o link no navegador, autorize o app e copie o `code` que aparece na URL de retorno. Troque esse `code` pelo token:

```powershell
python -m afiliado_bot mercadolivre-token --code "COLE_O_CODE_AQUI"
```

O comando vai mostrar `MERCADOLIVRE_ACCESS_TOKEN` e `MERCADOLIVRE_REFRESH_TOKEN`. Cole esses valores no `.env`. O access token expira, entao guarde tambem o refresh token.

Para descobrir o seu usuario a partir do token OAuth:

```powershell
python -m afiliado_bot mercadolivre-me
```

Esse comando chama `https://api.mercadolibre.com/users/me` usando `MERCADOLIVRE_ACCESS_TOKEN` e mostra `ID`, `Nickname`, `Nome`, `Site` e `Permalink`. Sem access token, esse endpoint nao retorna o seu usuario.

Sem access token, a alternativa e usar um link publico de anuncio seu. Se a API publica do item expuser `seller_id`, o bot mostra esse ID:

```powershell
python -m afiliado_bot mercadolivre-user-public --link "https://www.mercadolivre.com.br/..."
```

Tambem funciona colando o bloco promocional:

```powershell
@"
Cole este texto no buscador do Mercado Livre: G1Q50T-7TGA

Ou acesse o link:
https://meli.la/2v6vBf4
"@ | python -m afiliado_bot mercadolivre-user-public
```

Observacao: alguns links `meli.la` abrem uma pagina social/recomendacoes. Nesses casos, sem token, o Mercado Livre pode expor apenas nome publico do vendedor, produto e preco, mas nao o `seller_id`.

Na mineracao automatica, o conector tenta consultar tambem `items/{id}` e `users/{seller_id}` para preencher imagem melhor, quantidade vendida, loja oficial e reputacao do vendedor. Esses sinais entram no score e ajudam a evitar anunciantes com uma ou poucas vendas.

Configure o link de afiliado conforme o formato oficial do seu painel/programa:

```env
MERCADOLIVRE_AFFILIATE_TEMPLATE={url}
```

Se o programa fornecer um redirect com placeholders, use:

```env
MERCADOLIVRE_AFFILIATE_ID=seu_id
MERCADOLIVRE_AFFILIATE_TEMPLATE=https://seu-redirect-oficial.example/?url={encoded_url}&aff={affiliate_id}
```

## Shopee

Como o acesso afiliado/API da Shopee depende da conta e das credenciais aprovadas, o MVP nao faz scraping. Ele aceita:

- `SHOPEE_FEED_PATH`: arquivo `.json` ou `.csv` exportado/gerado a partir da plataforma oficial.
- `SHOPEE_PRODUCT_FEED_URL`: endpoint proprio que retorne JSON com produtos/ofertas.

Para a estrutura `ShopeeOfferV2`, o mapeamento usado e:

- `offerName` vira titulo da oferta;
- `offerLink` vira link afiliado usado no bot e na loja;
- `originalLink` fica como link original de referencia;
- `imageUrl` vira imagem da oferta;
- `commissionRate` entra no ranking;
- `categoryId`, `collectionId`, `offerType`, `periodStartTime` e `periodEndTime` ficam nos metadados.

Quando a oferta da Shopee nao trouxer preco, a loja e o Telegram mostram `Conferir preço` e enviam o usuario para `offerLink`.

Para endpoint/API, configure:

```env
SHOPEE_PRODUCT_FEED_URL=https://seu-endpoint-shopee
SHOPEE_SORT_TYPE=1
SHOPEE_START_PAGE=1
```

O sistema envia os parametros `keyword`, `sortType`, `page` e `limit`. Use `SHOPEE_SORT_TYPE=1` para novidades diarias e `SHOPEE_SORT_TYPE=2` para maior comissao.

Campos antigos de feed tambem continuam aceitos: `id`, `item_id`, `product_id`, `title`, `name`, `price`, `original_price`, `url`, `link`, `image_url`, `category`, `rating`, `sold_quantity`, `free_shipping`.

Para testar apenas com o feed exemplo da Shopee:

```powershell
$env:ENABLED_SOURCES="shopee"
$env:SHOPEE_FEED_PATH="data/shopee_products.example.json"
$env:KEYWORDS="fone bluetooth"
python -m afiliado_bot mine --limit-per-keyword 5
python -m afiliado_bot publish --limit 1 --dry-run
```

Nao use o arquivo `data/shopee_products.example.json` para publicar no Telegram; ele tem links ficticios e serve apenas para teste local.

## Amazon

A Amazon esta habilitada no minerador quando `amazon` estiver em `ENABLED_SOURCES` e pelo menos uma destas entradas estiver configurada:

- `AMAZON_CREATORS_CREDENTIAL_ID`, `AMAZON_CREATORS_CREDENTIAL_SECRET`, `AMAZON_CREATORS_VERSION` e `AMAZON_PARTNER_TAG`: Creators API oficial.
- `AMAZON_CREATORS_API_URL`: endpoint/proxy proprio da Creators API que retorne JSON.
- `AMAZON_PRODUCT_FEED_URL`: endpoint proprio que retorne JSON com produtos/ofertas.
- `AMAZON_FEED_PATH`: arquivo `.json` ou `.csv` exportado.
- `AMAZON_ACCESS_KEY`, `AMAZON_SECRET_KEY` e `AMAZON_PARTNER_TAG`: modo PA-API legado.

No painel da Amazon Creators API, copie `Credential ID`, `Credential Secret` e `Version`. Coloque no `.env`:

```env
ENABLED_SOURCES=mercadolivre,shopee,amazon,aliexpress
AMAZON_MODE=auto
AMAZON_PARTNER_TAG=seu-tag-20
AMAZON_CREATORS_CREDENTIAL_ID=seu_credential_id
AMAZON_CREATORS_CREDENTIAL_SECRET=seu_credential_secret
AMAZON_CREATORS_VERSION=3.1
AMAZON_MARKETPLACE=www.amazon.com.br
AMAZON_AFFILIATE_TEMPLATE=https://www.amazon.com.br/dp/{external_id}?tag={affiliate_id}&linkCode=ll1&language=pt_BR&ref_=as_li_ss_tl
```

> Nao use `AMAZON_AFFILIATE_TEMPLATE={url}`: isso publica o link **sem** a sua tag de associado, ou seja, manda trafego para a Amazon sem gerar comissao.

Teste as credenciais sem publicar:

```powershell
python -m afiliado_bot amazon-creators-test --keyword "fone bluetooth"
```

### Mais Vendidos da Amazon (sem API)

O comando `amazon-bestsellers` le as listas publicas **Mais Vendidos**
(`amazon.com.br/gp/bestsellers/<categoria>`), pega titulo, preco, nota, numero de
avaliacoes e imagem de cada item do ranking, monta o link com a sua tag de
associado e publica no Telegram. Nao precisa de PA-API nem da Creators API — o
unico requisito e `AMAZON_PARTNER_TAG`.

```env
AMAZON_PARTNER_TAG=seu-tag-20
AMAZON_BESTSELLERS_CATEGORIES=electronics,computers,videogames,appliances,kitchen,home,hpc,beauty,toys,sports,automotive,office-products
AMAZON_BESTSELLERS_LIMIT=8
```

```powershell
# ver o que sairia, sem enviar nada
python -m afiliado_bot amazon-bestsellers --dry-run

# so uma categoria
python -m afiliado_bot amazon-bestsellers --category videogames --limit-per-category 5

# minerar agora e deixar o comando `publish` postar depois
python -m afiliado_bot amazon-bestsellers --no-publish

# em loop, a cada INTERVAL_MINUTES
python -m afiliado_bot amazon-bestsellers --loop
```

Sem `AMAZON_PARTNER_TAG` o comando para com erro em vez de publicar link sem
comissao. As categorias sao lidas **uma por vez**, com pausa de
`AMAZON_BESTSELLERS_DELAY` segundos entre elas: leituras simultaneas fazem a
Amazon responder `503`. Mesmo assim o `503` acontece de forma aleatoria, entao
cada pagina e tentada `AMAZON_BESTSELLERS_ATTEMPTS` vezes com espera crescente, e
uma categoria que falhar nao derruba as outras.

Como o ranking nao informa preco "de", esses posts saem com o cabecalho
`TOP #N MAIS VENDIDOS` em vez de porcentagem de desconto.

No GitHub Actions esse passo ja roda junto da automacao a cada 8 minutos, desde
que voce cadastre a variavel `AMAZON_PARTNER_TAG` em
*Settings > Secrets and variables > Actions > Variables*. Sem ela, o passo e
pulado com um aviso.

Para fazer igual ao Mercado Livre, minerando automaticamente, atualizando o site e publicando no Telegram:

```powershell
python -m afiliado_bot auto-amazon --dry-run
python -m afiliado_bot auto-amazon --limit-per-keyword 3 --publish-limit 5
```

Para deixar em loop:

```powershell
python -m afiliado_bot auto-amazon --loop
```

O modo `auto` tenta Creators API, depois PA-API se as credenciais existirem, e por ultimo feed/export. Para feed local de teste:

```powershell
$env:ENABLED_SOURCES="amazon"
$env:AMAZON_FEED_PATH="data/amazon_products.example.json"
$env:AMAZON_PARTNER_TAG="seu-tag-20"
$env:AMAZON_AFFILIATE_TEMPLATE="{url}?tag={affiliate_id}"
python -m afiliado_bot mine --keyword "fone bluetooth" --limit-per-keyword 5
python -m afiliado_bot publish --limit 1 --dry-run
```

## AliExpress

O AliExpress tambem fica ativo quando `aliexpress` estiver em `ENABLED_SOURCES` e voce configurar API, endpoint ou feed:

- API oficial: `ALIEXPRESS_APP_KEY`, `ALIEXPRESS_APP_SECRET` e `ALIEXPRESS_TRACKING_ID`.
- Endpoint proprio: `ALIEXPRESS_PRODUCT_FEED_URL`, recebendo `keyword`, `q`, `page`, `limit` e `tracking_id`.
- Feed/export local: `ALIEXPRESS_FEED_PATH`.

Exemplo com API oficial:

```env
ALIEXPRESS_MODE=auto
ALIEXPRESS_APP_KEY=sua_app_key
ALIEXPRESS_APP_SECRET=seu_app_secret
ALIEXPRESS_TRACKING_ID=seu_tracking_id
ALIEXPRESS_TARGET_CURRENCY=BRL
ALIEXPRESS_TARGET_LANGUAGE=PT
ALIEXPRESS_SHIP_TO_COUNTRY=BR
```

Para teste local sem credenciais:

```powershell
$env:ENABLED_SOURCES="aliexpress"
$env:ALIEXPRESS_FEED_PATH="data/aliexpress_products.example.json"
python -m afiliado_bot mine --keyword "smartwatch" --limit-per-keyword 5
python -m afiliado_bot publish --limit 1 --dry-run
```

Nao publique os arquivos `data/amazon_products.example.json` e `data/aliexpress_products.example.json` como campanha real; eles servem apenas para validar o fluxo local.

## Outras redes

Use `SOCIAL_WEBHOOK_URLS` para integrar com fluxos externos. O sistema envia JSON com `message` e `product`.

Exemplo:

```env
SOCIAL_WEBHOOK_URLS=https://seu-n8n/webhook/ofertas
WHATSAPP_CHANNEL_URL=https://whatsapp.com/channel/0029Vb6G99PK0IBmcPVy8s2w
```

Para Instagram/Facebook/WhatsApp, o caminho correto e usar APIs oficiais ou um fluxo n8n/Make com suas credenciais aprovadas.

### Canal do WhatsApp

O canal publico foi ligado na loja como atalho:

```text
https://whatsapp.com/channel/0029Vb6G99PK0IBmcPVy8s2w
```

A WhatsApp Cloud API oficial envia mensagens para numeros de telefone de usuarios, nao para links de Canal do WhatsApp. Para automacao pelo bot, use `WHATSAPP_CHAT_IDS` somente com numeros com codigo do pais, ou use `SOCIAL_WEBHOOK_URLS` com um provedor externo que tenha suporte aprovado para publicar em canais.

Quando `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` e `WHATSAPP_CHAT_IDS` estiverem configurados, os comandos de publicacao enviam a mesma oferta para WhatsApp e Telegram. Produtos com imagem vao como imagem com legenda; produtos sem imagem vao como texto.

Para usar apenas Canal do WhatsApp, configure `SOCIAL_WEBHOOK_URLS` e `WHATSAPP_CHANNEL_URL`. O bot envia a oferta pronta para o webhook, mas o receptor ainda precisa ser um servico com suporte aprovado para publicar no Canal.

## Medir cliques

Se voce tiver um dominio publico apontando para a maquina/servidor, configure:

```env
PUBLIC_BASE_URL=https://ofertas.seudominio.com
```

Suba o redirect:

```powershell
python -m afiliado_bot serve --host 0.0.0.0 --port 8080
```

As mensagens usarao `https://ofertas.seudominio.com/r/{id}` e o sistema registrara eventos de clique no SQLite.

Tambem da para registrar venda manualmente:

```powershell
python -m afiliado_bot record-event --product-id 1 --event sale --channel mercado-livre
```

Esses eventos aumentam o peso das categorias que mais convertem.

## Estatisticas

```powershell
python -m afiliado_bot stats
```

## Loja online Lúmina Prime

O projeto tambem inclui uma loja estatica premium em `site/index.html`. Ela usa os produtos do banco exportados para `site/products.js`.

Depois de minerar produtos, atualize a vitrine:

```powershell
python -m afiliado_bot export-site
```

Abra no navegador:

```text
C:\Users\ADM\OneDrive\Documentos\Projeto_afiliado\site\index.html
```

A loja inclui:

- busca por produto, categoria ou marketplace;
- filtros por Mercado Livre, Shopee, Amazon, AliExpress e favoritos;
- ordenacao por curadoria, desconto e preco;
- cards com imagem, preco, desconto, frete, avaliacao e vendidos;
- gaveta de detalhes do produto;
- favoritos salvos no navegador;
- atalho para o canal publico do WhatsApp;
- botao de compra apontando para o link afiliado/exportado.

## Rodar sem deixar o computador ligado

Este projeto ja inclui um agendador em `.github/workflows/affiliate-automation.yml` para rodar no GitHub Actions. Ele faz, a cada 8 minutos:

1. restaura o banco SQLite do bot pelo cache do GitHub Actions;
2. roda os testes;
3. minera ofertas com `python -m afiliado_bot mine`;
4. publica no Telegram com `python -m afiliado_bot publish`;
5. exporta a loja com `python -m afiliado_bot export-site`;
6. publica a pasta `site` no GitHub Pages.

Para ativar:

1. Envie o projeto para um repositorio no GitHub.
2. No GitHub, va em `Settings > Pages` e selecione `GitHub Actions` como origem.
3. No GitHub, va em `Settings > Secrets and variables > Actions`.
4. Em `Secrets`, cadastre no minimo:

```text
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_IDS
```

Use `TELEGRAM_CHAT_IDS` com o canal/grupo, por exemplo `@PromoLinkBrasil99`. O bot precisa estar nesse canal/grupo com permissao para publicar.

Cadastre tambem os secrets das lojas que voce for usar:

```text
MERCADOLIVRE_ACCESS_TOKEN
MERCADOLIVRE_REFRESH_TOKEN
AMAZON_CREATORS_CREDENTIAL_ID
AMAZON_CREATORS_CREDENTIAL_SECRET
AMAZON_ACCESS_KEY
AMAZON_SECRET_KEY
ALIEXPRESS_APP_KEY
ALIEXPRESS_APP_SECRET
SHOPEE_AUTHORIZATION_HEADER
WHATSAPP_ACCESS_TOKEN
WHATSAPP_PHONE_NUMBER_ID
WHATSAPP_CHAT_IDS
SOCIAL_WEBHOOK_URLS
```

Para usar somente webhook/Pipedream para o Canal do WhatsApp, `SOCIAL_WEBHOOK_URLS` tambem pode ficar em `Variables`. Se ele estiver em `Secrets`, o valor secreto tem prioridade.

Em `Variables`, voce pode ajustar a automacao sem mexer no codigo:

```text
KEYWORDS=fone bluetooth,smartwatch,air fryer,furadeira,utensilios de cozinha,acessorios carro
ENABLED_SOURCES=mercadolivre,amazon,aliexpress,shopee,manual
MINE_LIMIT_PER_KEYWORD=10
PUBLISH_LIMIT=1
REPOST_AFTER_MINUTES=8
MIN_SCORE_TO_PUBLISH=25
SITE_EXPORT_LIMIT=120
AMAZON_PARTNER_TAG=seu-tag-20
AMAZON_AFFILIATE_TEMPLATE={url}?tag={affiliate_id}
MERCADOLIVRE_AFFILIATE_TEMPLATE={url}
ALIEXPRESS_TRACKING_ID=seu_tracking_id
SOCIAL_WEBHOOK_URLS=https://seu-webhook-pipedream
WHATSAPP_GRAPH_API_VERSION=v25.0
WHATSAPP_CHANNEL_URL=https://whatsapp.com/channel/0029Vb6G99PK0IBmcPVy8s2w
```

Depois disso, abra a aba `Actions`, escolha `Agendador Afiliado` e rode manualmente uma vez. Se quiser testar sem publicar no Telegram, use `Run workflow` com `dry_run=true`.

Observacao: GitHub Actions nao e servidor 24h. Ele e bom para tarefas agendadas, como postar ofertas de tempos em tempos. O site funciona no GitHub Pages porque e estatico. Ja o servidor Python `python -m afiliado_bot serve`, usado para `/r/{id}` e medicao de cliques, precisa de uma hospedagem com processo continuo, como VPS, Render, Railway ou Fly.io.

## Proximos passos recomendados

- Ligar os endpoints oficiais/proxies aprovados de cada marketplace quando suas credenciais estiverem disponiveis.
- Criar dashboard web para aprovar/rejeitar ofertas antes da publicacao.
- Adicionar encurtador oficial, UTM e tags por canal.
- Hospedar o redirect em VPS para medir cliques reais.
- Criar tarefas no Agendador do Windows para rodar `mine` e `publish` em horarios fixos.
