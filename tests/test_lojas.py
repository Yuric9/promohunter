import pytest

from app import issues, monitor
from app.config import settings
from app.services import lojas

VTEX = [
    {"productName": "Tênis Mizuno Wave Rider 28", "link": "https://www.mizuno.com.br/tenis-wave-rider-28/p",
     "items": [{"images": [{"imageUrl": "https://img/rider.jpg"}],
                "sellers": [{"commertialOffer": {"Price": 559.99, "ListPrice": 899.99, "AvailableQuantity": 3}}]}]},
    {"productName": "Camiseta Mizuno Run", "link": "https://www.mizuno.com.br/camiseta/p",
     "items": [{"images": [], "sellers": [{"commertialOffer": {"Price": 89.9, "ListPrice": 99.9, "AvailableQuantity": 5}}]}]},
    {"productName": "Tênis esgotado", "link": "https://www.mizuno.com.br/esgotado/p",
     "items": [{"images": [], "sellers": [{"commertialOffer": {"Price": 100, "ListPrice": 300, "AvailableQuantity": 0}}]}]},
]

SHOPIFY = {"products": [
    {"title": "Bermuda Linho Masculina", "handle": "bermuda-linho", "images": [{"src": "https://img/bermuda.jpg"}],
     "variants": [{"price": "199.00", "compare_at_price": "199.00", "available": True},
                  {"price": "139.00", "compare_at_price": "199.00", "available": True}]},
    {"title": "Camisa Polo", "handle": "polo", "images": [],
     "variants": [{"price": "159.00", "compare_at_price": None, "available": True}]},
]}


class Resposta:
    def __init__(self, status, dados):
        self.status_code, self._dados = status, dados

    def json(self):
        if isinstance(self._dados, str):
            raise ValueError("não é JSON")
        return self._dados


@pytest.fixture(autouse=True)
def isolar(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    postados = []
    monkeypatch.setattr(monitor, "enviar_telegram", lambda texto, imagem="": postados.append(texto) or {"ok": True})
    return postados


def falsa_internet(monkeypatch, paginas):
    pedidos = []

    def get(url, headers=None, timeout=None):
        pedidos.append(url)
        for trecho, resposta in paginas.items():
            if trecho in url:
                return resposta
        return Resposta(404, "não achei")
    monkeypatch.setattr(lojas.requests, "get", get)
    return pedidos


def test_vtex_calcula_desconto_e_ignora_esgotados(monkeypatch):
    pedidos = falsa_internet(monkeypatch, {"/api/catalog_system/": Resposta(200, VTEX)})
    produtos = lojas.buscar_na_loja("https://www.mizuno.com.br/ofertas")
    assert [p.titulo for p in produtos] == ["Tênis Mizuno Wave Rider 28", "Camiseta Mizuno Run"]
    rider = produtos[0]
    assert (rider.preco, rider.preco_original, rider.desconto, rider.plataforma) == (559.99, 899.99, 38, "VTEX")
    assert "OrderByBestDiscountDESC" in pedidos[0]
    # com busca, só ficam os produtos com as palavras no nome
    assert [p.titulo for p in lojas.buscar_na_loja("mizuno.com.br", "tenis")] == ["Tênis Mizuno Wave Rider 28"]
    assert "ft=tenis" in pedidos[-1]


def test_palavras_no_titulo_ignoram_acento_genero_e_plural():
    assert lojas.tem_palavras("Tênis de Corrida Masculino Mizuno", "tenis masculina")
    assert lojas.tem_palavras("Camiseta Masculina Regular", "camisetas masculino")
    assert not lojas.tem_palavras("Escrivaninha com gaveta para notebook", "notebook dell")


def test_loja_que_nao_aceita_ordenacao_tenta_sem_ordenar(monkeypatch):
    def get(url, headers=None, timeout=None):
        return Resposta(200, [] if "OrderBy" in url else VTEX)
    monkeypatch.setattr(lojas.requests, "get", get)
    assert len(lojas.buscar_na_loja("aramis.com.br", plataforma="vtex")) == 2


def test_shopify_usa_a_variante_com_maior_desconto_e_filtra_palavras(monkeypatch):
    falsa_internet(monkeypatch, {"/products.json": Resposta(200, SHOPIFY)})
    produtos = lojas.buscar_na_loja("insiderstore.com.br", "bermuda")
    assert len(produtos) == 1
    p = produtos[0]
    assert (p.preco, p.preco_original, p.desconto) == (139.0, 199.0, 30)
    assert p.link == "https://insiderstore.com.br/products/bermuda-linho" and p.plataforma == "Shopify"


def test_loja_sem_vtex_nem_shopify_explica_o_erro(monkeypatch):
    falsa_internet(monkeypatch, {})
    with pytest.raises(lojas.LojaNaoSuportada, match="não é VTEX nem Shopify"):
        lojas.buscar_na_loja("https://www.kabum.com.br")


def test_monitor_posta_so_descontos_de_20_por_cento_no_formato_padrao(monkeypatch, isolar):
    falsa_internet(monkeypatch, {"/api/catalog_system/": Resposta(200, VTEX)})
    cfg = monitor.Monitoramento(lojas=[{"site": "https://www.mizuno.com.br"}])
    assert monitor.executar(cfg)["postados"] == 1
    texto = isolar[0]
    assert "Tênis Mizuno Wave Rider 28" in texto and "Preço antigo: R$ 899,99" in texto
    assert "Preço novo: R$ 559,99" in texto and "Desconto: 38%" in texto
    assert "https://www.mizuno.com.br/tenis-wave-rider-28/p" in texto
    # na próxima execução a mesma oferta não é repetida
    assert monitor.executar(cfg)["postados"] == 0


def test_loja_exclui_palavras_e_nao_repete_o_mesmo_produto_em_outra_cor(monkeypatch, isolar):
    def produto(nome, cor):
        return {"productName": nome, "link": f"https://loja/{nome}-{cor}/p".replace(" ", "-"),
                "items": [{"images": [], "sellers": [{"commertialOffer": {"Price": 50, "ListPrice": 100, "AvailableQuantity": 1}}]}]}
    dados = [produto("Camiseta Básica - Azul", "azul"), produto("Camiseta Básica - Preta", "preta"),
             produto("Body Bebê Reserva Mini", "x")]
    falsa_internet(monkeypatch, {"/api/catalog_system/": Resposta(200, dados)})
    cfg = monitor.Monitoramento(lojas=[{"site": "usereserva.com", "excluir": ["bebê", "infantil"]}])
    assert monitor.executar(cfg)["postados"] == 1
    assert "Camiseta Básica" in isolar[0]


def test_execucao_automatica_so_roda_o_que_e_gratis():
    cfg = monitor.Monitoramento(
        produtos=[{"termo": "tênis"}], voos=[{"origem": "GYN", "destino": "REC", "ida_em_dias": 5}],
        anuncios=[{"feeds": ["https://blog/feed"]}, {"busca": "promo"}], lojas=[{"site": "mizuno.com.br"}],
    )
    gratis = cfg.so_gratis()
    assert gratis.total_buscas() == 0
    assert len(gratis.lojas) == 1 and len(gratis.anuncios) == 1 and not gratis.produtos and not gratis.voos


def test_formulario_de_loja():
    corpo = ("### Site da loja\n\nhttps://www.mizuno.com.br\n\n### Só produtos com estas palavras\n\ntênis corrida\n\n"
             "### Desconto mínimo (%)\n\n25\n\n### Preço máximo (R$)\n\n_No response_\n")
    tipo, dados = issues.interpretar(corpo)
    assert tipo == "loja"
    item = monitor.ItemLoja(**dados)
    assert (item.site, item.busca, item.desconto_min, item.preco_max) == ("https://www.mizuno.com.br", "tênis corrida", 25, None)
    assert "www.mizuno.com.br" in monitor.descrever("loja", item, None)


def test_limite_de_posts_por_execucao(monkeypatch, isolar):
    falsa_internet(monkeypatch, {"/api/catalog_system/": Resposta(200, VTEX), "/products.json": Resposta(200, SHOPIFY)})
    cfg = monitor.Monitoramento(lojas=[{"site": "mizuno.com.br", "plataforma": "vtex"},
                                       {"site": "insiderstore.com.br", "plataforma": "shopify"}])
    assert monitor.executar(cfg, limite=1)["postados"] == 1
    assert monitor.executar(cfg, limite=1)["postados"] == 1  # a oferta que ficou de fora sai na próxima
    assert len(isolar) == 2 and "Bermuda" in isolar[1]


def test_posts_sao_intercalados_entre_as_lojas(monkeypatch, isolar):
    def produtos(prefixo):
        return [lojas.Produto(titulo=f"{prefixo} {n}", preco=50, preco_original=100, desconto=50,
                              link=f"https://{prefixo}/{n}", plataforma="VTEX") for n in range(3)]
    monkeypatch.setattr(monitor, "buscar_na_loja", lambda site, busca, plataforma: produtos(site))
    cfg = monitor.Monitoramento(lojas=[{"site": "tenis"}, {"site": "roupa"}, {"site": "tech"}])
    assert monitor.executar(cfg, limite=4)["postados"] == 4
    assert [t.split("<b>")[1].split("</b>")[0] for t in isolar] == ["tenis 0", "roupa 0", "tech 0", "tenis 1"]


def test_inicio_gira_a_ordem_das_lojas(monkeypatch, isolar):
    def produtos(prefixo):
        return [lojas.Produto(titulo=f"{prefixo} 0", preco=50, preco_original=100, desconto=50,
                              link=f"https://{prefixo}/0", plataforma="VTEX")]
    monkeypatch.setattr(monitor, "buscar_na_loja", lambda site, busca, plataforma: produtos(site))
    cfg = monitor.Monitoramento(lojas=[{"site": "tenis"}, {"site": "roupa"}, {"site": "tech"}])
    monitor.executar(cfg, limite=1, inicio=2)
    assert "tech 0" in isolar[0]
