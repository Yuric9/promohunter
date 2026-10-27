"""
Robô de conversa do Telegram: você escreve o que quer ("iphone 17 128gb",
"passagem goiânia recife 20/12 a 27/12", "pousada em pirenópolis 15/11 2 noites")
e ele pesquisa na hora e responde com as melhores opções.

Funciona só na conversa direta com o robô (nada é postado em canal).
Só o dono pode usar, para ninguém gastar suas buscas: quem for administrador do canal
TELEGRAM_CHAT_ID, ou o usuário cujo número estiver em TELEGRAM_DONO.
Roda na Vercel: api/telegram.py recebe as mensagens e chama processar().
"""
import hashlib
import logging
from datetime import date
from typing import Optional

import requests

from app import monitor
from app.config import settings
from app.interpretador import Pedido, interpretar
from app.services.viagens import buscar_voos

log = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/{metodo}"

AJUDA = (
    "👋 <b>Oi! Eu sou o PromoHunter.</b>\n\n"
    "Me diga o que você quer e eu pesquiso agora, comparando vários sites:\n\n"
    "🛒 <b>Produto</b>\n<code>iphone 17 128gb</code>\n<code>air fryer até 400</code>\n\n"
    "✈️ <b>Passagem</b>\n<code>passagem goiânia recife 20/12 a 27/12</code>\n"
    "<code>voo de brasília para salvador 05/01 2 pessoas</code>\n\n"
    "🏨 <b>Hotel ou pousada</b>\n<code>pousada em pirenópolis 15/11 2 noites</code>\n"
    "<code>hotel caldas novas 20/11 a 23/11 até 300</code>"
)


def segredo_webhook() -> str:
    """Senha que o Telegram envia junto com cada mensagem (derivada do token, sem configuração extra)."""
    return hashlib.sha256(f"promohunter:{settings.telegram_bot_token}".encode()).hexdigest()[:48]


def telegram(metodo: str, **dados) -> dict:
    r = requests.post(API.format(token=settings.telegram_bot_token, metodo=metodo), json=dados, timeout=20)
    resposta = r.json() if r.content else {}
    if not resposta.get("ok"):
        log.warning("Telegram %s falhou: %s", metodo, resposta.get("description"))
    return resposta


def responder(chat_id: int, texto: str, imagem: str = ""):
    if imagem.startswith("http") and len(texto) <= 1024:  # legenda de foto aceita até 1024 caracteres
        if telegram("sendPhoto", chat_id=chat_id, photo=imagem, caption=texto, parse_mode="HTML").get("ok"):
            return
    telegram("sendMessage", chat_id=chat_id, text=texto, parse_mode="HTML", disable_web_page_preview=True)


def autorizado(user_id: int) -> bool:
    """Só o dono pode pesquisar: o número em TELEGRAM_DONO ou um administrador do canal."""
    if settings.telegram_dono and str(user_id) == settings.telegram_dono.strip():
        return True
    if not settings.telegram_chat_id:
        return False
    membro = telegram("getChatMember", chat_id=settings.telegram_destino, user_id=user_id)
    return (membro.get("result") or {}).get("status") in ("creator", "administrator")


def pesquisar(pedido: Pedido, hoje: Optional[date] = None):
    """Faz a busca pedida e devolve (texto, imagem). Gasta 1 busca da SerpApi."""
    hoje = hoje or date.today()
    if pedido.tipo == "voo":
        if pedido.ida < hoje:
            return "📅 Essa data já passou. Me mande uma data futura.", ""
        res = buscar_voos(pedido.origem, pedido.destino, pedido.ida, pedido.volta, pedido.adultos)
        if not res.voos:
            return f"😕 Não encontrei voos de {pedido.nome_origem} para {pedido.nome_destino} nessa data.", ""
        voos = [v for v in res.voos if not pedido.preco_max or v.preco <= pedido.preco_max]
        if not voos:
            return (f"😕 O voo mais barato de {pedido.nome_origem} para {pedido.nome_destino} está "
                    f"{monitor._brl(res.voos[0].preco)}, acima do seu limite de {monitor._brl(pedido.preco_max)}."), ""
        res.voos = voos
        rota = f"{pedido.nome_origem} → {pedido.nome_destino}"
        return monitor.formatar_voos(rota, pedido.ida, pedido.volta, pedido.adultos, res), ""

    if pedido.tipo == "hospedagem":
        if pedido.ida < hoje:
            return "📅 Essa data já passou. Me mande uma data futura.", ""
        item = monitor.ItemHospedagem(local=pedido.local, checkin=pedido.ida, noites=pedido.noites,
                                      adultos=pedido.adultos, diaria_max=pedido.preco_max)
        posts = monitor.posts_hospedagem(item, hoje)
        if not posts:
            return f"😕 Não encontrei opções para “{pedido.local}” nessas datas" + \
                (f" com diária até {monitor._brl(pedido.preco_max)}." if pedido.preco_max else "."), ""
        return posts[0].texto, posts[0].imagem

    posts = monitor.posts_produto(monitor.ItemProduto(termo=pedido.termo, preco_max=pedido.preco_max))
    if not posts:
        return f"😕 Não encontrei “{pedido.termo}”" + \
            (f" até {monitor._brl(pedido.preco_max)}." if pedido.preco_max else ". Tente escrever de outro jeito."), ""
    return posts[0].texto, posts[0].imagem


def processar(update: dict):
    """Trata uma mensagem recebida do Telegram."""
    msg = update.get("message") or {}
    texto = (msg.get("text") or "").strip()
    chat = msg.get("chat") or {}
    if not texto or chat.get("type") != "private":
        return  # só conversa direta com o robô
    if not autorizado(msg["from"]["id"]):
        responder(chat["id"], "🔒 Este robô é particular.\n\nSe ele é seu, cadastre na Vercel a variável "
                  f"<code>TELEGRAM_DONO</code> com o valor <code>{msg['from']['id']}</code> (seu número no Telegram).")
        return
    if texto.lower() in ("/start", "/ajuda", "ajuda", "/help", "oi", "olá", "ola"):
        responder(chat["id"], AJUDA)
        return

    pedido = interpretar(texto)
    if pedido.faltando:
        responder(chat["id"], "🤔 Para pesquisar, me diga também " + " e ".join(pedido.faltando)
                  + ".\n\nExemplo: <code>passagem goiânia recife 20/12 a 27/12</code>\nMande /ajuda para ver mais exemplos.")
        return
    descricao = {"voo": f"✈️ {pedido.nome_origem} → {pedido.nome_destino}",
                 "hospedagem": f"🏨 {pedido.local}", "produto": f"🛒 {pedido.termo}"}[pedido.tipo]
    responder(chat["id"], f"🔎 Pesquisando {descricao}...")
    telegram("sendChatAction", chat_id=chat["id"], action="typing")
    try:
        resultado, imagem = pesquisar(pedido)
    except Exception as e:
        log.exception("Falha na pesquisa")
        responder(chat["id"], f"❌ Não consegui pesquisar agora: {e}")
        return
    responder(chat["id"], resultado, imagem)


def configurar_webhook(url: str) -> dict:
    """Diz ao Telegram para entregar as mensagens do robô neste endereço."""
    return telegram("setWebhook", url=url, secret_token=segredo_webhook(),
                    allowed_updates=["message"], drop_pending_updates=True)
