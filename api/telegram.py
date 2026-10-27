"""
Endpoint do robô de conversa na Vercel.
- POST /api/telegram: o Telegram entrega aqui as mensagens que você manda para o robô.
- GET  /api/telegram?configurar=1: liga o robô a este endereço (abra uma vez no navegador).
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import bot  # noqa: E402
from app.config import settings  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def _enviar(self, status: int, texto: str, tipo: str = "text/plain; charset=utf-8"):
        corpo = texto.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_POST(self):
        if self.headers.get("X-Telegram-Bot-Api-Secret-Token") != bot.segredo_webhook():
            return self._enviar(403, "proibido")
        tamanho = int(self.headers.get("Content-Length") or 0)
        try:
            bot.processar(json.loads(self.rfile.read(tamanho) or b"{}"))
        except Exception as e:  # responde 200 mesmo assim, para o Telegram não reenviar sem parar
            print("Erro ao processar mensagem:", repr(e))
        self._enviar(200, "ok")

    def do_GET(self):
        faltando = [n for n, v in (("SERPAPI_KEY", settings.serpapi_key), ("TELEGRAM_BOT_TOKEN", settings.telegram_bot_token)) if not v]
        if faltando:
            return self._enviar(500, "Faltam as variáveis na Vercel: " + ", ".join(faltando))
        if "configurar" in parse_qs(urlparse(self.path).query):
            url = f"https://{self.headers.get('Host')}/api/telegram"
            r = bot.configurar_webhook(url)
            if r.get("ok"):
                return self._enviar(200, "✅ Robô ligado! Abra o Telegram e mande uma mensagem para o seu robô (ex.: /ajuda).")
            return self._enviar(500, f"❌ O Telegram recusou: {r.get('description')}")
        info = bot.telegram("getWebhookInfo").get("result") or {}
        ligado = info.get("url", "").endswith("/api/telegram")
        self._enviar(200, "✅ Robô ligado e esperando mensagens." if ligado else
                     "⚠️ Robô ainda não ligado. Abra este endereço com ?configurar=1 no final.")
