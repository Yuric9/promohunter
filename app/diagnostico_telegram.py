"""
Diagnóstico do Telegram: mostra qual robô o token representa e em quais canais/grupos
ele está, com o endereço exato para usar no TELEGRAM_CHAT_ID.
Uso: python -m app.diagnostico_telegram   (ou "Diagnosticar Telegram" no GitHub Actions)
"""
import sys

import requests

from app.config import settings

API = "https://api.telegram.org/bot{token}/{metodo}"


def chamar(metodo: str, **params) -> dict:
    r = requests.get(API.format(token=settings.telegram_bot_token, metodo=metodo), params=params, timeout=15)
    return r.json() if r.content else {"ok": False, "description": f"HTTP {r.status_code}"}


def endereco(chat: dict) -> str:
    return f"@{chat['username']}" if chat.get("username") else str(chat["id"])


def main() -> int:
    if not settings.telegram_bot_token:
        print("❌ TELEGRAM_BOT_TOKEN não está cadastrado.")
        return 1
    eu = chamar("getMe")
    if not eu.get("ok"):
        print(f"❌ Token recusado pelo Telegram ({eu.get('description')}). Gere outro com /revoke no BotFather.")
        return 1
    print(f"✅ Token válido: robô @{eu['result']['username']} ({eu['result']['first_name']})\n")

    original = settings.telegram_chat_id
    alvo = settings.telegram_destino
    print(f"TELEGRAM_CHAT_ID cadastrado: {len(original)} caractere(s); usado como: {alvo}")
    if alvo.startswith("+"):
        print("⚠️ Isso é um link de CONVITE de canal privado. Deixe o canal público e use o link público dele.")
    info = chamar("getChat", chat_id=alvo) if alvo else {"ok": False, "description": "vazio"}
    if info.get("ok"):
        c = info["result"]
        print(f"✅ O Telegram encontrou: {c.get('title')} ({c.get('type')}) → {endereco(c)}")
        membro = chamar("getChatMember", chat_id=alvo, user_id=eu["result"]["id"])
        status = (membro.get("result") or {}).get("status", "?")
        pode = (membro.get("result") or {}).get("can_post_messages")
        print(f"   Situação do robô nesse chat: {status}" + (" (pode publicar ✅)" if pode else ""))
        if status not in ("administrator", "creator"):
            print("   ⚠️ O robô precisa ser ADMINISTRADOR do canal com a permissão 'Publicar mensagens'.")
    else:
        print(f"❌ O Telegram não encontrou esse chat ({info.get('description')}).")

    print("\nCanais/grupos onde o robô apareceu recentemente:")
    vistos = {}
    for u in chamar("getUpdates", allowed_updates='["channel_post","message","my_chat_member"]').get("result", []):
        for chave in ("channel_post", "message", "my_chat_member", "edited_channel_post"):
            chat = (u.get(chave) or {}).get("chat")
            if chat and chat.get("type") != "private":
                vistos[chat["id"]] = chat
    if not vistos:
        print("   (nenhum) → publique qualquer mensagem no canal (ex.: 'teste') e rode o diagnóstico de novo.")
    for chat in vistos.values():
        print(f"   • {chat.get('title')} ({chat.get('type')}) → use no TELEGRAM_CHAT_ID: {endereco(chat)}")
    return 0 if info.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
