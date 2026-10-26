import pytest
from fastapi.testclient import TestClient

from app import main, storage
from app.config import settings
from app.models import Produto
from app.services import busca
from app.services.comparador import comparar_termo, rankear_melhores
from app.services.whatsapp import formatar_mensagem


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
    monkeypatch.setattr(busca, "FONTES", {"Fake": lambda termo, limite: list(PRODUTOS)})
    enviados = []
    monkeypatch.setattr(main, "enviar_whatsapp", lambda msg, n=None, g=None: enviados.append(msg) or {"ok": True})
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
    monkeypatch.setattr(busca, "FONTES", {"Fake": lambda t, l: list(PRODUTOS), "Quebrada": quebra})
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
    monkeypatch.setattr(busca, "FONTES", {"Shopee": sem_internet})
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
