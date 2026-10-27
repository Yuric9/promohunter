import pytest
from fastapi.testclient import TestClient

from app import main, storage
from app.config import settings
from app.models import Produto
from app.services import busca
from app.services.comparador import comparar_termo, rankear_melhores
from app.services.telegram import formatar_mensagem


def produto(titulo, preco, original=None, desconto=0, plataforma="Shopee", vendidos=0):
    return Produto(titulo=titulo, preco=preco, preco_original=original, desconto=desconto,
                   link=f"https://x/{titulo}", plataforma=plataforma, vendidos=vendidos)


PRODUTOS = [
    produto("ps5 slim", 3000, 4000, 25, "Mercado Livre", 500),
    produto("ps5 usado", 2500, None, 0, "Shopee", 10),
    produto("controle ps5", 300, 450, 33, "Shopee", 2000),
]


@pytest.fixture(autouse=True)
def isolar(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "api_key", "segredo")
    monkeypatch.setattr(busca, "fontes_ativas", lambda: {"Fake": lambda termo, limite: list(PRODUTOS)})
    enviados = []
    monkeypatch.setattr(main, "enviar_telegram", lambda msg, imagem="": enviados.append(msg) or {"ok": True})
    return enviados


client = TestClient(main.app)
AUTH = {"X-API-Key": "segredo"}


def test_sem_api_key_e_recusado():
    assert client.get("/api/configuracoes").status_code == 401
    assert client.get("/api/configuracoes", headers={"X-API-Key": "errada"}).status_code == 401
    assert client.get("/api/configuracoes", headers=AUTH).status_code == 200


def test_filtro_de_desconto_e_respeitado():
    assert rankear_melhores(PRODUTOS, desconto_min=90) == []
    assert all(p.desconto >= 25 for p in rankear_melhores(PRODUTOS, desconto_min=25))


def test_economia_usa_preco_original_da_propria_oferta():
    comp = comparar_termo("ps5", PRODUTOS, desconto_min=20, preco_min=1000)
    assert comp.melhor_oferta.titulo == "ps5 slim"
    assert comp.economia == 1000


def test_mensagem_sem_preco_original_nao_mostra_de_por():
    comp = comparar_termo("ps5", [PRODUTOS[1]], desconto_min=0)
    msg = formatar_mensagem(comp)
    assert "De " not in msg and "R$ 2.500,00" in msg


def test_falha_de_uma_fonte_vira_aviso(monkeypatch):
    def quebra(termo, limite):
        raise RuntimeError("bloqueado")
    monkeypatch.setattr(busca, "fontes_ativas", lambda: {"Fake": lambda t, l: list(PRODUTOS), "Quebrada": quebra})
    r = client.get("/api/promocoes/buscar", params={"q": "ps5"}, headers=AUTH).json()
    assert r["total"] == 3
    assert r["avisos"] == ["Quebrada: bloqueado"]


def test_job_nao_reenvia_mesma_oferta(isolar):
    storage.save_config(storage.SearchConfig(termos=["ps5"], desconto_min=20, preco_max=5000))
    main.job()
    main.job()
    assert len(isolar) == 1


def test_iniciar_status_e_parar_automacao():
    assert client.post("/api/automacao/iniciar", headers=AUTH).status_code == 200
    assert client.get("/api/automacao/status", headers=AUTH).json()["rodando"] is True
    client.post("/api/automacao/parar", headers=AUTH)
    assert client.get("/api/automacao/status", headers=AUTH).json()["rodando"] is False


def test_painel_e_saude_abrem_sem_chave():
    r = client.get("/")
    assert r.status_code == 200 and "PromoHunter" in r.text
    assert client.get("/saude").json()["status"] == "PromoHunter rodando"


def test_erro_de_conexao_vira_mensagem_amigavel(monkeypatch):
    import requests

    def sem_internet(termo, limite):
        raise requests.ConnectionError("HTTPSConnectionPool(...)")
    monkeypatch.setattr(busca, "fontes_ativas", lambda: {"Shopee": sem_internet})
    r = client.get("/api/promocoes/buscar", params={"q": "ps5"}, headers=AUTH).json()
    assert r["avisos"] == ["Shopee: não foi possível conectar. Verifique sua internet."]


def test_shopee_afiliados_assina_e_converte(monkeypatch):
    import hashlib
    import json as _json

    from app.services import shopee

    monkeypatch.setattr(settings, "shopee_app_id", "123")
    monkeypatch.setattr(settings, "shopee_secret", "abc")
    capturado = {}

    class Resposta:
        status_code = 200
        content = b"x"

        def raise_for_status(self):
            pass

        def json(self):
            return {"data": {"productOfferV2": {"nodes": [{
                "productName": "Air Fryer", "priceMin": "300.00", "priceDiscountRate": 25, "sales": 1500,
                "ratingStar": "4.8", "imageUrl": "https://img/x.jpg", "shopName": "Loja",
                "productLink": "https://shopee.com.br/p", "offerLink": "https://s.shopee.com.br/afiliado",
            }]}}}

    def falso_post(url, data, headers, timeout):
        capturado.update(url=url, corpo=data.decode(), auth=headers["Authorization"])
        return Resposta()

    monkeypatch.setattr(shopee.requests, "post", falso_post)
    produtos = shopee.buscar_shopee('air "fryer"', 5)

    assert capturado["url"].endswith("affiliate.shopee.com.br/graphql")
    assert 'keyword: "air \\"fryer\\""' in _json.loads(capturado["corpo"])["query"]
    ts = capturado["auth"].split("Timestamp=")[1].split(",")[0]
    esperado = hashlib.sha256(f"123{ts}{capturado['corpo']}abc".encode()).hexdigest()
    assert capturado["auth"] == f"SHA256 Credential=123, Timestamp={ts}, Signature={esperado}"

    p = produtos[0]
    assert (p.preco, p.desconto, p.preco_original, p.vendidos) == (300.0, 25, 400.0, 1500)
    assert p.link == "https://s.shopee.com.br/afiliado"


def test_shopee_afiliados_erro_vira_mensagem(monkeypatch):
    import pytest as _pytest

    from app.services import shopee

    monkeypatch.setattr(settings, "shopee_app_id", "123")
    monkeypatch.setattr(settings, "shopee_secret", "errada")

    class Resposta:
        status_code = 200
        content = b"x"

        def raise_for_status(self):
            pass

        def json(self):
            return {"errors": [{"message": "Invalid Signature", "extensions": {"code": 10020}}]}

    monkeypatch.setattr(shopee.requests, "post", lambda *a, **k: Resposta())
    with _pytest.raises(RuntimeError, match="10020.*Invalid Signature"):
        shopee.buscar_shopee("ps5")


def test_integracoes_nao_revela_chaves(monkeypatch):
    monkeypatch.setattr(settings, "shopee_app_id", "123")
    monkeypatch.setattr(settings, "shopee_secret", "segredo-shopee")
    r = client.get("/api/integracoes", headers=AUTH)
    assert r.json()["shopee_afiliados"] is True
    assert "segredo-shopee" not in r.text


class RespostaFalsa:
    def __init__(self, dados, status=200):
        self.dados, self.status_code, self.content = dados, status, b"x"

    def raise_for_status(self):
        pass

    def json(self):
        return self.dados


def test_google_shopping_converte_resultados(monkeypatch):
    from app.services import google_shopping

    monkeypatch.setattr(settings, "serpapi_key", "k")
    capturado = {}

    def falso_get(url, params, timeout):
        capturado.update(params)
        return RespostaFalsa({"shopping_results": [
            {"title": "Air Fryer Mondial", "extracted_price": 299.9, "extracted_old_price": 399.9,
             "source": "Magazine Luiza", "product_link": "https://google/p/1", "thumbnail": "https://img/1",
             "rating": 4.7, "reviews": 1200},
            {"title": "Air Fryer Philco", "price": "R$ 1.299,90", "tag": "20% OFF", "source": "Amazon",
             "link": "https://amazon/x"},
            {"title": "Sem preço", "source": "Loja"},
        ]})

    monkeypatch.setattr(google_shopping.requests, "get", falso_get)
    produtos = google_shopping.buscar_google_shopping("air fryer")

    assert (capturado["engine"], capturado["gl"], capturado["q"]) == ("google_shopping", "br", "air fryer")
    a, b = produtos  # o item sem preço é ignorado
    assert (a.preco, a.preco_original, a.desconto, a.loja, a.link) == (299.9, 399.9, 25, "Magazine Luiza", "https://google/p/1")
    assert (b.preco, b.desconto, b.preco_original, b.link) == (1299.9, 20, 1624.88, "https://amazon/x")


def test_google_shopping_erro_da_serpapi(monkeypatch):
    import pytest as _pytest

    from app.services import google_shopping

    monkeypatch.setattr(google_shopping.requests, "get",
                        lambda *a, **k: RespostaFalsa({"error": "Invalid API key."}, 401))
    with _pytest.raises(RuntimeError, match="Invalid API key"):
        google_shopping.buscar_google_shopping("ps5")


def test_sem_nenhuma_chave_avisa_como_configurar(monkeypatch):
    from app.services import busca as _busca

    monkeypatch.undo()
    for campo in ("serpapi_key", "shopee_app_id", "shopee_secret", "ml_access_token"):
        monkeypatch.setattr(settings, campo, "")
    r = _busca.buscar_todas("ps5")
    assert r.produtos == [] and "SERPAPI_KEY" in r.avisos[0]


def test_telegram_envia_foto_e_cai_para_texto(monkeypatch):
    from app.services import telegram

    monkeypatch.setattr(settings, "telegram_bot_token", "123:ABC")
    monkeypatch.setattr(settings, "telegram_chat_id", "@meucanal")
    chamadas = []

    def falso_post(url, json, timeout):
        metodo = url.rsplit("/", 1)[1]
        chamadas.append((metodo, json))
        if metodo == "sendPhoto":
            return RespostaFalsa({"ok": False, "description": "wrong file identifier"})
        return RespostaFalsa({"ok": True})

    monkeypatch.setattr(telegram.requests, "post", falso_post)
    comp = comparar_termo("ps5 <slim>", [PRODUTOS[0]], desconto_min=0)
    texto = formatar_mensagem(comp)
    assert telegram.enviar_telegram(texto, "https://img/x.jpg") == {"ok": True}
    assert [c[0] for c in chamadas] == ["sendPhoto", "sendMessage"]
    assert chamadas[1][1]["chat_id"] == "@meucanal" and chamadas[1][1]["parse_mode"] == "HTML"
    assert "PS5 &lt;SLIM&gt;" in texto and "<s>R$ 4.000,00</s>" in texto


def test_telegram_sem_configuracao(monkeypatch):
    from app.services import telegram

    monkeypatch.setattr(settings, "telegram_bot_token", "")
    assert telegram.enviar_telegram("oi")["ok"] is False


def test_telegram_chat_not_found_explica_o_problema(monkeypatch):
    from app.services import telegram

    monkeypatch.setattr(settings, "telegram_bot_token", "123:ABC")
    monkeypatch.setattr(settings, "telegram_chat_id", "@errado")
    chamadas = []

    def falso_post(url, json, timeout):
        chamadas.append(url)
        return RespostaFalsa({"ok": False, "description": "Bad Request: chat not found"})

    monkeypatch.setattr(telegram.requests, "post", falso_post)
    r = telegram.enviar_telegram("oi", "https://img/x.jpg")
    assert r["ok"] is False and "link público do canal" in r["erro"]
    assert len(chamadas) == 1  # não tenta de novo sem a foto


def test_diagnostico_telegram_mostra_endereco_certo(monkeypatch, capsys):
    from app import diagnostico_telegram as d

    monkeypatch.setattr(settings, "telegram_bot_token", "123:ABC")
    monkeypatch.setattr(settings, "telegram_chat_id", "@promos_do_yuri")
    respostas = {
        "getMe": {"ok": True, "result": {"id": 1, "username": "yuri_promos_bot", "first_name": "@promos_do_yuri"}},
        "getChat": {"ok": False, "description": "Bad Request: chat not found"},
        "getUpdates": {"ok": True, "result": [
            {"channel_post": {"chat": {"id": -1001234, "title": "Promos do Yuri 🔥", "type": "channel", "username": "promosdoyuri"}}},
            {"message": {"chat": {"id": 5, "type": "private"}}},
        ]},
    }
    monkeypatch.setattr(d, "chamar", lambda metodo, **p: respostas[metodo])
    assert d.main() == 1
    saida = capsys.readouterr().out
    assert "robô @yuri_promos_bot" in saida and "não encontrou" in saida
    assert "Promos do Yuri 🔥 (channel) → use no TELEGRAM_CHAT_ID: @promosdoyuri" in saida
