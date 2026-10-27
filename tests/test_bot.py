from datetime import date

import pytest

from app import bot
from app.config import settings
from app.models import ResultadoVoos, Voo


@pytest.fixture
def tg(monkeypatch):
    """Telegram falso: guarda o que o robô enviaria."""
    monkeypatch.setattr(settings, "telegram_bot_token", "123:ABC")
    monkeypatch.setattr(settings, "telegram_chat_id", "-1004362267617")
    monkeypatch.setattr(settings, "telegram_dono", "")
    enviados, admins = [], {42}

    def falso(metodo, **dados):
        if metodo == "getChatMember":
            return {"ok": True, "result": {"status": "administrator" if dados["user_id"] in admins else "left"}}
        enviados.append((metodo, dados))
        return {"ok": True}

    monkeypatch.setattr(bot, "telegram", falso)
    return enviados


def mensagem(texto, user=42, tipo="private"):
    return {"message": {"text": texto, "chat": {"id": 7, "type": tipo}, "from": {"id": user}}}


def textos(enviados):
    return [d.get("text") or d.get("caption") for m, d in enviados if m in ("sendMessage", "sendPhoto")]


def test_estranho_nao_pesquisa(tg, monkeypatch):
    monkeypatch.setattr(bot, "pesquisar", lambda p: pytest.fail("não deveria pesquisar"))
    bot.processar(mensagem("iphone 17", user=999))
    assert "particular" in textos(tg)[0] and "999" in textos(tg)[0]


def test_dono_pelo_numero(tg, monkeypatch):
    monkeypatch.setattr(settings, "telegram_dono", "999")
    monkeypatch.setattr(bot, "pesquisar", lambda p: ("🛒 resultado", ""))
    bot.processar(mensagem("iphone 17", user=999))
    assert textos(tg) == ["🔎 Pesquisando 🛒 iphone 17...", "🛒 resultado"]


def test_ajuda(tg):
    bot.processar(mensagem("/start"))
    assert "Eu sou o PromoHunter" in textos(tg)[0]


def test_pedido_incompleto_pergunta(tg, monkeypatch):
    monkeypatch.setattr(bot, "pesquisar", lambda p: pytest.fail("não deveria pesquisar"))
    bot.processar(mensagem("passagem goiania recife"))
    assert "data de ida" in textos(tg)[0]


def test_mensagem_em_grupo_ou_canal_e_ignorada(tg):
    bot.processar(mensagem("iphone 17", tipo="channel"))
    assert tg == []


def test_voo_responde_com_os_mais_baratos(tg, monkeypatch):
    res = ResultadoVoos(voos=[Voo(preco=1089, companhia="LATAM", duracao_min=175),
                              Voo(preco=1890, companhia="GOL", escalas=1, duracao_min=300)],
                        nivel_preco="low", link="https://google.com/travel/flights")
    capturado = {}

    def falso_buscar(origem, destino, ida, volta, adultos):
        capturado.update(origem=origem, destino=destino, ida=ida, volta=volta)
        return res

    monkeypatch.setattr(bot, "buscar_voos", falso_buscar)
    bot.processar(mensagem("passagem goiânia recife 20/12/2030 a 27/12/2030 até 1500"))
    resposta = textos(tg)[-1]
    assert capturado == {"origem": "GYN", "destino": "REC", "ida": date(2030, 12, 20), "volta": date(2030, 12, 27)}
    assert "Goiânia → Recife" in resposta and "R$ 1.089,00" in resposta and "R$ 1.890,00" not in resposta
    assert "ABAIXO do normal" in resposta


def test_erro_na_pesquisa_e_avisado(tg, monkeypatch):
    def quebra(p):
        raise RuntimeError("SerpApi: limite do plano atingido")
    monkeypatch.setattr(bot, "pesquisar", quebra)
    bot.processar(mensagem("iphone 17"))
    assert "limite do plano" in textos(tg)[-1]


def test_resposta_longa_vai_como_texto_e_curta_com_foto(tg):
    bot.responder(7, "x" * 1500, "https://img/a.jpg")
    bot.responder(7, "curto", "https://img/a.jpg")
    assert [m for m, _ in tg] == ["sendMessage", "sendPhoto"]


def test_segredo_do_webhook_depende_do_token(monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "1:A")
    a = bot.segredo_webhook()
    monkeypatch.setattr(settings, "telegram_bot_token", "1:B")
    assert a != bot.segredo_webhook() and len(a) == 48


def test_endpoint_da_vercel_recusa_sem_segredo(monkeypatch):
    import io
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("api_telegram", Path(__file__).resolve().parent.parent / "api" / "telegram.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    processados = []
    monkeypatch.setattr(modulo.bot, "processar", processados.append)

    class Falso(modulo.handler):
        def __init__(self, segredo):
            self.headers = {"X-Telegram-Bot-Api-Secret-Token": segredo, "Content-Length": "2"}
            self.rfile, self.wfile, self.status = io.BytesIO(b"{}"), io.BytesIO(), None

        def send_response(self, codigo):
            self.status = codigo

        def send_header(self, *a):
            pass

        def end_headers(self):
            pass

    errado = Falso("errado"); errado.do_POST()
    certo = Falso(modulo.bot.segredo_webhook()); certo.do_POST()
    assert (errado.status, certo.status, processados) == (403, 200, [{}])
