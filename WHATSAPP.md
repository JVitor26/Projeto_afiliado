# Integracao com WhatsApp

## Canal atual

O canal informado foi adicionado como link publico da loja:

```text
https://whatsapp.com/channel/0029Vb6G99PK0IBmcPVy8s2w
```

A API oficial WhatsApp Cloud API envia mensagens para numeros de telefone de usuarios pelo recurso de numero comercial. Ela nao aceita esse link de Canal do WhatsApp como destinatario direto. Por isso, nao coloque `https://whatsapp.com/channel/...` em `WHATSAPP_CHAT_IDS`.

## Opcao 1: WhatsApp Cloud API

Use esta opcao para enviar as mesmas ofertas do Telegram para numeros de telefone com opt-in, usando a API oficial da Meta. Quando o produto tem imagem, o bot envia a imagem com a legenda da oferta. Quando nao tem imagem, envia a mensagem em texto.

### Setup

1. Acesse o Meta Business e configure WhatsApp Business Platform.
2. Copie suas credenciais:
   - `WHATSAPP_ACCESS_TOKEN`: token de acesso.
   - `WHATSAPP_PHONE_NUMBER_ID`: ID do numero comercial.
3. Informe os destinatarios em `WHATSAPP_CHAT_IDS`, sempre com codigo do pais.

### Configurar no `.env`

```env
WHATSAPP_ACCESS_TOKEN=seu_access_token_aqui
WHATSAPP_PHONE_NUMBER_ID=seu_phone_number_id
WHATSAPP_CHAT_IDS=55XXXXXXXXXXX
WHATSAPP_GRAPH_API_VERSION=v25.0
```

Para mais de um destinatario:

```env
WHATSAPP_CHAT_IDS=5511999999999,5565999999999
```

### Testar

```bash
echo "https://amzn.to/SEU_LINK" | python -m afiliado_bot link-offer
```

Depois de configurado, qualquer comando que publique ofertas tambem tentara enviar no WhatsApp:

```bash
python -m afiliado_bot publish --limit 1
python -m afiliado_bot auto-mercadolivre
```

## Opcao 2: Webhook externo

Use `SOCIAL_WEBHOOK_URLS` para enviar a oferta para um fluxo externo como n8n, Make ou outro provedor aprovado. Essa e a configuracao para tentar publicar somente no Canal do WhatsApp, desde que o servico que recebe o webhook tenha suporte para isso.

```env
SOCIAL_WEBHOOK_URLS=https://seu-n8n-webhook-url
WHATSAPP_CHANNEL_URL=https://whatsapp.com/channel/0029Vb6G99PK0IBmcPVy8s2w
```

Para usar apenas o canal via webhook, deixe `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_IDS`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` e `WHATSAPP_CHAT_IDS` vazios no GitHub Actions. Configure somente:

```text
SOCIAL_WEBHOOK_URLS
WHATSAPP_CHANNEL_URL
```

O bot envia JSON com `message`, `message_text`, `target`, `whatsapp_channel` e `product`. O bloco `whatsapp_channel` vem pronto para o receptor publicar:

```json
{
  "target": {
    "type": "whatsapp_channel",
    "url": "https://whatsapp.com/channel/0029Vb6G99PK0IBmcPVy8s2w"
  },
  "whatsapp_channel": {
    "url": "https://whatsapp.com/channel/0029Vb6G99PK0IBmcPVy8s2w",
    "send_mode": "image",
    "text": "*Nome do produto* | Por *R$ 99,90*",
    "image_url": "https://..."
  }
}
```

Se o provedor que voce escolher tiver uma integracao legitima com Canal do WhatsApp, ele deve receber esse webhook e fazer a publicacao por la.

## Qual escolher?

| Cenario | Configuracao |
|---------|--------------|
| Link para usuarios entrarem no canal | Ja esta no site |
| Enviar para numeros autorizados | `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_CHAT_IDS` |
| Publicar em Canal do WhatsApp | Use um provedor/webhook que ofereca suporte oficial ou aprovado |
