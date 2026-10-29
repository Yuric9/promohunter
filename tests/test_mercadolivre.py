import pytest

from app import monitor
from app.config import settings
from app.services import lojas, mercadolivre

RESULTADOS = {"results": [
    {"title": "Tênis Masculino Olympikus Corre 3", "price": 249.9, "original_price": 399.9, "condition": "new",
     "permalink": "https://produto.mercadolivre.com.br/MLB-1", "thumbnail": "https://img/1-I.jpg",
     "seller": {"nickname": "OLYMPIKUS"}},
    {"title": "Tênis Masculino Usado", "price": 50, "original_price": 300, "condition": "used",
     "permalink": "https://produto.mercadolivre.com.br/MLB-2"},
    {"title": "Meia Esportiva", "price": 20, "condition": "new", "permalink": "https://produto.mercadolivre.com.br/MLB-3"},
]}


class Resposta:
    def __init__(self, status, dados):
        self.status_code, self._dados, self.content, self.text = status, dados, b"x", str(dados)

    def json(self):
        return self._dados

    def raise_for_status(self):
        pass


@pytest.fixture(autouse=True)
def isolar(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "historico_min_dias", 0)
    monkeypatch.setattr(settings, "ml_access_token", "")
    monkeypatch.setattr(settings, "ml_client_id", "123")
    monkeypatch.setattr(settings, "ml_client_secret", "segredo")
    monkeypatch.setitem(mercadolivre._token, "valor", "")
    postados = []
    monkeypatch.setattr(monitor, "enviar_telegram", lambda texto, imagem="": postados.append(texto) or {"ok": True})
    return postados


def test_pega_a_chave_sozinho_e_busca_so_produtos_novos(monkeypatch):
    pedidos = []
    monkeypatch.setattr(mercadolivre.requests, "post", lambda url, data, headers, timeout: pedidos.append(data)
                        or Resposta(200, {"access_token": "APP_USR-1", "expires_in": 21600}))

    def get(url, params, headers, timeout):
        assert headers["Authorization"] == "Bearer APP_USR-1"
        return Resposta(200, RESULTADOS)
    monkeypatch.setattr(mercadolivre.requests, "get", get)
    produtos = lojas.buscar_na_loja("https://www.mercadolivre.com.br", "tênis masculino")
    mercadolivre.buscar_mercadolivre("outra busca")  # reaproveita a chave
    assert [p.titulo for p in produtos] == ["Tênis Masculino Olympikus Corre 3"]
    p = produtos[0]
    assert (p.preco, p.preco_original, p.desconto, p.plataforma) == (249.9, 399.9, 38, "Mercado Livre")
    assert len(pedidos) == 1 and pedidos[0]["grant_type"] == "client_credentials"


def test_chave_recusada_explica_o_que_conferir(monkeypatch):
    monkeypatch.setattr(mercadolivre.requests, "post", lambda *a, **k: Resposta(401, {"message": "invalid client"}))
    with pytest.raises(RuntimeError, match="Confira ML_CLIENT_ID e ML_CLIENT_SECRET"):
        mercadolivre.buscar_mercadolivre("tênis")


def test_sem_aplicativo_o_monitor_pula_o_mercado_livre_sem_erro(monkeypatch, isolar):
    monkeypatch.setattr(settings, "ml_client_id", "")
    cfg = monitor.Monitoramento(lojas=[{"site": "https://www.mercadolivre.com.br", "busca": "tênis masculino"}])
    assert monitor.executar(cfg) == {"postados": 0, "repetidos": 0, "erros": 0}
