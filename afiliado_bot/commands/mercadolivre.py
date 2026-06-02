"""Helpers de autenticação e tokens Mercado Livre."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def build_auth_url(client_id: str, redirect_uri: str, *, state: str = "") -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
    }
    if state:
        params["state"] = state
    return "https://auth.mercadolivre.com.br/authorization?" + urlencode(params)


def exchange_code(
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    *,
    code_verifier: str = "",
) -> dict[str, object]:
    form: dict[str, str] = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
    }
    if code_verifier:
        form["code_verifier"] = code_verifier
    return _post_token(form)


def refresh_token(client_id: str, client_secret: str, refresh_token_value: str) -> dict[str, object]:
    form = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token_value,
    }
    return _post_token(form)


def fetch_me(token: str) -> dict[str, object]:
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


def append_github_env(github_env: str, key: str, value: str) -> None:
    with Path(github_env).open("a", encoding="utf-8") as file:
        file.write(f"{key}<<EOF\n{value}\nEOF\n")


def _post_token(form: dict[str, str]) -> dict[str, object]:
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
