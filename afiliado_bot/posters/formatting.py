from __future__ import annotations

import re
from html import unescape


def format_for_whatsapp(message: str) -> str:
    text = message or "Nova oferta"
    text = re.sub(r"<b>(.*?)</b>", r"*\1*", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<strong>(.*?)</strong>", r"*\1*", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<s>(.*?)</s>", r"~\1~", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<strike>(.*?)</strike>", r"~\1~", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    return unescape(text).strip() or "Nova oferta"


def compact_response(*parts: str) -> str:
    return " | ".join(part for part in parts if part)[:500]
