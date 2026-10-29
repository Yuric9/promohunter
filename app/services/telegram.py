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


DICAS = {
    "chat not found": "o TELEGRAM_CHAT_ID não corresponde a um canal público. Confira o link do canal "
                      "(ex.: t.me/promos_do_yuri) — não use o nome do robô nem um link de convite privado",
    "unauthorized": "o TELEGRAM_BOT_TOKEN está errado ou foi trocado no /revoke",
    "not enough rights": "o robô não é administrador do canal com permissão de publicar",
    "bot is not a member": "o robô não foi adicionado ao canal",
}


def _explicar(erro: str) -> str:
    for trecho, dica in DICAS.items():
        if trecho in erro.lower():
            return f"{erro} → {dica}"
    return erro


def _chamar(metodo: str, dados: dict) -> dict:
    r = requests.post(API.format(token=settings.telegram_bot_token, metodo=metodo), json=dados, timeout=15)
    resposta = r.json() if r.content else {}
    if not resposta.get("ok"):
        raise RuntimeError(_explicar(resposta.get("description") or f"HTTP {r.status_code}"))
    return resposta


def enviar_telegram(texto: str, imagem: str = "") -> dict:
    """Posta no canal/grupo configurado. Com imagem vai como foto com legenda."""
    if not (settings.telegram_bot_token and settings.telegram_chat_id):
        return {"ok": False, "erro": "Telegram não configurado (TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID)"}
    base = {"chat_id": settings.telegram_destino, "parse_mode": "HTML"}
    try:
        if imagem.startswith("http"):
            try:
                _chamar("sendPhoto", {**base, "photo": imagem, "caption": texto})
                return {"ok": True}
            except RuntimeError as e:
                if "→" in str(e):
                    raise  # erro de configuração: não adianta tentar sem a foto
                # imagem recusada pelo Telegram: manda só o texto
        _chamar("sendMessage", {**base, "text": texto})
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "erro": str(e)}


def enviar_privado(chat_id: str, texto: str) -> dict:
    """Mensagem direta para uma pessoa (ex.: relatório de status para o dono), fora do canal."""
    if not (settings.telegram_bot_token and chat_id):
        return {"ok": False, "erro": "falta TELEGRAM_BOT_TOKEN ou o número do destinatário"}
    try:
        _chamar("sendMessage", {"chat_id": chat_id, "text": texto, "parse_mode": "HTML",
                                "disable_web_page_preview": True})
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "erro": str(e)}
