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

    alvo = settings.telegram_destino
    # O log do GitHub é público: nunca mostrar o valor cadastrado, só o tipo dele.
    if alvo.startswith("+"):
        tipo = "link de CONVITE (t.me/+...) ⚠️ não funciona: use o link público do canal ou o id numérico"
    elif alvo.startswith("@"):
        tipo = f"nome de canal público ({len(alvo) - 1} letras)"
    elif alvo.lstrip("-").isdigit():
        tipo = "id numérico"
    else:
        tipo = "vazio" if not alvo else "formato desconhecido"
    print(f"TELEGRAM_CHAT_ID cadastrado: {tipo}")
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

    # Relatório no privado (TELEGRAM_DONO): sem mostrar o número no log público
    dono = settings.dono_chat_id
    if not settings.telegram_dono:
        print("\nTELEGRAM_DONO: não cadastrado (o relatório de status no privado fica desligado).")
    else:
        bruto = settings.telegram_dono
        print(f"\nTELEGRAM_DONO cadastrado: {len(dono)} dígitos"
              + (" ⚠️ tinha outros caracteres além dos números (foram ignorados)" if bruto.strip() != dono else ""))
        r = chamar("getChat", chat_id=dono) if dono else {"ok": False, "description": "sem números"}
        if r.get("ok"):
            print(f"✅ O Telegram encontrou a conversa com {r['result'].get('first_name', '')}: o relatório pode ser enviado.")
        else:
            print(f"❌ O Telegram não encontrou a conversa ({r.get('description')}). Confira se o número é o do "
                  f"@userinfobot e se você tocou em Iniciar no robô @{eu['result']['username']}.")

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
