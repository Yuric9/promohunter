from html import escape

import requests

from app.config import settings
from app.models import Comparativo

API = "https://api.telegram.org/bot{token}/{metodo}"


def _brl(valor: float) -> str:
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def formatar_mensagem(comp: Comparativo) -> str:
    """Mensagem em HTML (formato aceito pelo Telegram). Cabe na legenda de uma foto (1024 caracteres)."""
    m = comp.melhor_oferta
    titulo = m.titulo if len(m.titulo) <= 150 else m.titulo[:147] + "..."
    loja = m.loja or m.plataforma
    desconto = f" · <b>{m.desconto}% OFF</b>" if m.desconto else ""
    if m.preco_original:
        preco = f"💰 De <s>{_brl(m.preco_original)}</s> por <b>{_brl(m.preco)}</b>\n💵 Economia de {_brl(comp.economia)}"
    else:
        preco = f"💰 <b>{_brl(m.preco)}</b>"
    return (
        f"🔥 <b>{escape(comp.termo.upper())}</b>\n\n"
        f"🏪 {escape(loja)}{desconto}\n"
        f"📦 {escape(titulo)}\n"
        f"{preco}\n\n"
        f'🔗 <a href="{escape(m.link, quote=True)}">Ver oferta</a>'
    )


def _chamar(metodo: str, dados: dict) -> dict:
    r = requests.post(API.format(token=settings.telegram_bot_token, metodo=metodo), json=dados, timeout=15)
    resposta = r.json() if r.content else {}
    if not resposta.get("ok"):
        raise RuntimeError(resposta.get("description") or f"HTTP {r.status_code}")
    return resposta


def enviar_telegram(texto: str, imagem: str = "") -> dict:
    """Posta no canal/grupo configurado. Com imagem vai como foto com legenda."""
    if not (settings.telegram_bot_token and settings.telegram_chat_id):
        return {"ok": False, "erro": "Telegram não configurado (TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID)"}
    base = {"chat_id": settings.telegram_chat_id, "parse_mode": "HTML"}
    try:
        if imagem.startswith("http"):
            try:
                _chamar("sendPhoto", {**base, "photo": imagem, "caption": texto})
                return {"ok": True}
            except RuntimeError:
                pass  # imagem recusada pelo Telegram: manda só o texto
        _chamar("sendMessage", {**base, "text": texto})
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "erro": str(e)}
