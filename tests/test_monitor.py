from datetime import date
from pathlib import Path

import pytest

from app import monitor
from app.config import settings
from app.models import Anuncio, Hospedagem, Produto, ResultadoVoos, Voo

HOJE = date(2026, 11, 1)


@pytest.fixture(autouse=True)
def isolar(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    postados = []
    monkeypatch.setattr(monitor, "enviar_telegram", lambda texto, imagem="": postados.append(texto) or {"ok": True})
    return postados


def test_arquivo_de_exemplo_do_repositorio_e_valido():
    cfg = monitor.carregar(Path(__file__).resolve().parent.parent / "monitoramento.yml")
    assert cfg.total_buscas() * 30 <= monitor.BUSCAS_GRATIS_MES


def test_exemplos_comentados_do_arquivo_sao_validos(tmp_path):
    original = (Path(__file__).resolve().parent.parent / "monitoramento.yml").read_text(encoding="utf-8")
    linhas = [l[3:] if l.startswith("#  ") and not l.startswith("#  =") else "" for l in original.splitlines()]
    inicio = next(i for i, l in enumerate(linhas) if l.startswith("produtos:"))
    fim = next(i for i, l in enumerate(linhas) if l.startswith("⚠️"))
    arquivo = tmp_path / "m.yml"
    arquivo.write_text("\n".join(linhas[inicio:fim]), encoding="utf-8")
    cfg = monitor.carregar(arquivo)
    assert cfg.produtos and cfg.voos and cfg.hospedagens and cfg.anuncios


def test_datas_relativas_e_fixas():
    voo = monitor.ItemVoo(origem="gyn", destino="rec", ida_em_dias=10, duracao_dias=7)
    assert voo.datas(HOJE) == (date(2026, 11, 11), date(2026, 11, 18))
    assert monitor.ItemVoo(origem="GYN", destino="REC", ida="2026-12-20").datas(HOJE) == (date(2026, 12, 20), None)
    with pytest.raises(ValueError):
        monitor.ItemVoo(origem="GYN", destino="REC")


def resultado_voos(preco, nivel):
    return ResultadoVoos(
        voos=[Voo(preco=preco, companhia="LATAM", escalas=0, duracao_min=175),
              Voo(preco=preco + 300, companhia="GOL", escalas=1, duracao_min=300)],
        nivel_preco=nivel, faixa_tipica=[1400, 2100], link="https://google.com/travel/flights?x=1",
    )


def test_voo_preco_baixo_e_postado_com_selo(monkeypatch, isolar):
    monkeypatch.setattr(monitor, "buscar_voos", lambda *a: resultado_voos(980, "low"))
    cfg = monitor.Monitoramento(voos=[{"origem": "GYN", "destino": "REC", "ida_em_dias": 30, "duracao_dias": 7,
                                       "so_preco_baixo": True}])
    assert monitor.executar(cfg, hoje=HOJE)["postados"] == 1
    texto = isolar[0]
    assert "GYN → REC" in texto and "ABAIXO do normal" in texto and "R$ 980,00" in texto
    assert "R$ 1.400,00 a R$ 2.100,00" in texto and "LATAM · direto · 2h55" in texto

    # mesma oferta no dia seguinte não é repetida
    assert monitor.executar(cfg, hoje=HOJE)["repetidos"] == 1


def test_voo_preco_normal_acima_do_limite_nao_posta(monkeypatch, isolar):
    monkeypatch.setattr(monitor, "buscar_voos", lambda *a: resultado_voos(1800, "typical"))
    cfg = monitor.Monitoramento(voos=[{"origem": "GYN", "destino": "REC", "ida_em_dias": 30,
                                       "preco_max": 1500, "so_preco_baixo": True}])
    assert monitor.executar(cfg, hoje=HOJE)["postados"] == 0 and isolar == []


def test_voo_com_data_que_ja_passou_e_ignorado(monkeypatch):
    chamado = []
    monkeypatch.setattr(monitor, "buscar_voos", lambda *a: chamado.append(1))
    cfg = monitor.Monitoramento(voos=[{"origem": "GYN", "destino": "REC", "ida": "2026-10-01"}])
    assert monitor.executar(cfg, hoje=HOJE)["postados"] == 0 and chamado == []


def test_hospedagem_filtra_nota_e_preco_e_prioriza_oferta(monkeypatch, isolar):
    opcoes = [
        Hospedagem(nome="Pousada Barata Ruim", diaria=120, nota=3.2, link="https://a"),
        Hospedagem(nome="Pousada Boa", diaria=250, total=500, nota=4.6, link="https://b", imagem="https://img/b"),
        Hospedagem(nome="Pousada em Promoção", diaria=280, nota=4.8, link="https://c", oferta="25% abaixo do normal"),
        Hospedagem(nome="Hotel Caro", diaria=900, nota=4.9, link="https://d"),
    ]
    monkeypatch.setattr(monitor, "buscar_hospedagens", lambda *a: opcoes)
    cfg = monitor.Monitoramento(hospedagens=[{"local": "pousadas em Pirenópolis", "checkin_em_dias": 20,
                                              "noites": 2, "diaria_max": 400, "nota_min": 4.0}])
    monitor.executar(cfg, hoje=HOJE)
    texto = isolar[0]
    assert texto.index("Pousada em Promoção") < texto.index("Pousada Boa")
    assert "Barata Ruim" not in texto and "Hotel Caro" not in texto
    assert "25% abaixo do normal" in texto and "21/11/2026 a 23/11/2026" in texto


def test_anuncios_novos_sao_postados_uma_vez(monkeypatch, isolar):
    anuncios = [Anuncio(titulo=f"Promo {i}", link=f"https://site/{i}", resumo="Passagens a partir de R$ 199")
                for i in range(5)]
    monkeypatch.setattr(monitor, "buscar_anuncios", lambda busca, dias, sites: anuncios)
    cfg = monitor.Monitoramento(anuncios=[{"busca": "promoção passagens", "maximo_por_vez": 2}])
    assert monitor.executar(cfg, hoje=HOJE)["postados"] == 2
    assert monitor.executar(cfg, hoje=HOJE)["postados"] == 2  # os próximos 2, sem repetir
    assert len({t.split("<b>Promo ")[1][0] for t in isolar}) == 4


def test_produto_usa_filtros(monkeypatch, isolar):
    produtos = [
        Produto(titulo="Air Fryer A", preco=450, preco_original=600, desconto=25, link="https://a", plataforma="Google Shopping", loja="Magalu"),
        Produto(titulo="Air Fryer B", preco=700, preco_original=1000, desconto=30, link="https://b", plataforma="Google Shopping"),
    ]
    monkeypatch.setattr(monitor, "buscar_google_shopping", lambda termo: produtos)
    cfg = monitor.Monitoramento(produtos=[{"termo": "air fryer", "preco_max": 600, "desconto_min": 15}])
    monitor.executar(cfg, hoje=HOJE)
    assert "Air Fryer A" in isolar[0] and "R$ 450,00" in isolar[0]


def test_produto_mensagem_contem_apenas_os_cinco_campos(monkeypatch, isolar):
    produtos = [
        Produto(titulo="Tênis de corrida", preco=240, preco_original=300, desconto=20,
                link="https://loja.exemplo/produto", plataforma="G", loja="Loja Exemplo"),
    ]
    monkeypatch.setattr(monitor, "buscar_google_shopping", lambda termo: produtos)
    cfg = monitor.Monitoramento(produtos=[{"termo": "tênis"}])
    monitor.executar(cfg, hoje=HOJE)
    texto = isolar[0]
    assert "Tênis de corrida" in texto
    assert "Preço antigo: R$ 300,00" in texto
    assert "Preço novo: R$ 240,00" in texto
    assert "Desconto: 20%" in texto
    assert "https://loja.exemplo/produto" in texto
    assert "Loja Exemplo" not in texto
    assert "Economia" not in texto and "Mais baratas encontradas" not in texto


def test_produto_com_desconto_abaixo_de_20_nao_passa_no_filtro_padrao(monkeypatch, isolar):
    produtos = [
        Produto(titulo="Tênis casual", preco=90, preco_original=100, desconto=10,
                link="https://loja.exemplo/tenis", plataforma="G"),
    ]
    monkeypatch.setattr(monitor, "buscar_google_shopping", lambda termo: produtos)
    cfg = monitor.Monitoramento(produtos=[{"termo": "tênis"}])
    monitor.executar(cfg, hoje=HOJE)
    assert isolar == []


def test_erro_em_um_item_nao_para_os_outros(monkeypatch, isolar):
    def quebra(*a):
        raise RuntimeError("SerpApi: Invalid API key.")
    monkeypatch.setattr(monitor, "buscar_voos", quebra)    monkeypatch.setattr(monitor, "buscar_anuncios", lambda b, d, s: [Anuncio(titulo="X", link="https://x")])
    cfg = monitor.Monitoramento(voos=[{"origem": "GYN", "destino": "REC", "ida_em_dias": 5}],
                                anuncios=[{"busca": "promo"}])
    assert monitor.executar(cfg, hoje=HOJE) == {"postados": 1, "repetidos": 0, "erros": 1}


def test_simular_nao_posta(monkeypatch, isolar, caplog):
    caplog.set_level("INFO")
    monkeypatch.setattr(monitor, "buscar_anuncios", lambda b, d, s: [Anuncio(titulo="Oferta", link="https://o")])
    monitor.executar(monitor.Monitoramento(anuncios=[{"busca": "promo"}]), simular=True, hoje=HOJE)
    assert isolar == [] and "simulação" in caplog.text


def test_main_avisa_yaml_quebrado(tmp_path, monkeypatch, caplog):
    arquivo = tmp_path / "m.yml"
    arquivo.write_text("voos:\n  - origem: GYN\n   destino: REC\n", encoding="utf-8")
    monkeypatch.setenv("MONITORAMENTO", str(arquivo))
    assert monitor.main() == 1
    assert "erro de formatação" in caplog.text


class RespostaFalsa:
    def __init__(self, dados):
        self.dados, self.status_code, self.content = dados, 200, b"x"

    def raise_for_status(self):
        pass

    def json(self):
        return self.dados


def test_leitura_google_voos(monkeypatch):
    from app.services import viagens

    capturado = {}

    def falso_get(url, params, timeout):
        capturado.update(params)
        return RespostaFalsa({
            "search_metadata": {"google_flights_url": "https://www.google.com/travel/flights?x"},
            "best_flights": [{"price": 1290, "total_duration": 175, "flights": [
                {"airline": "LATAM", "departure_airport": {"id": "GYN", "time": "2026-12-16 06:00"},
                 "arrival_airport": {"id": "REC"}}]}],
            "other_flights": [{"price": 990, "total_duration": 320, "flights": [
                {"airline": "GOL", "departure_airport": {"id": "GYN"}, "arrival_airport": {"id": "BSB"}},
                {"airline": "Azul", "departure_airport": {"id": "BSB"}, "arrival_airport": {"id": "REC"}}]},
                {"total_duration": 100, "flights": []}],
            "price_insights": {"lowest_price": 990, "price_level": "low", "typical_price_range": [1300, 1900]},
        })

    monkeypatch.setattr(viagens.requests, "get", falso_get)
    res = viagens.buscar_voos("gyn", "rec", date(2026, 12, 16), date(2026, 12, 23))
    assert (capturado["engine"], capturado["type"], capturado["return_date"], capturado["currency"]) == \
        ("google_flights", 1, "2026-12-23", "BRL")
    assert [v.preco for v in res.voos] == [990, 1290]  # mais barato primeiro
    assert res.voos[0].companhia == "Azul + GOL" and res.voos[0].escalas == 1
    assert res.nivel_preco == "low" and res.faixa_tipica == [1300, 1900] and res.link.startswith("https://www.google")


def test_leitura_google_hoteis(monkeypatch):
    from app.services import viagens

    monkeypatch.setattr(viagens.requests, "get", lambda url, params, timeout: RespostaFalsa({
        "search_metadata": {"google_hotels_url": "https://www.google.com/travel/hotels?x"},
        "properties": [
            {"name": "Pousada do Sol", "rate_per_night": {"lowest": "R$ 310", "extracted_lowest": 310},
             "total_rate": {"extracted_lowest": 620}, "overall_rating": 4.7, "reviews": 812,
             "images": [{"thumbnail": "https://img/sol"}], "deal_description": "Deal", "deal": "20% less than usual"},
            {"name": "Sem preço"},
            {"name": "Pousada Simples", "rate_per_night": {"extracted_lowest": 180}, "overall_rating": 4.1,
             "deal": "Great Deal"},
        ],
    }))
    hs = viagens.buscar_hospedagens("pousadas em Pirenópolis", date(2026, 11, 21), date(2026, 11, 23))
    assert [h.nome for h in hs] == ["Pousada Simples", "Pousada do Sol"]
    sol = hs[1]
    assert (sol.diaria, sol.total, sol.nota, sol.imagem, sol.oferta) == (310, 620, 4.7, "https://img/sol", "Promoção · 20% abaixo do normal")
    assert hs[0].link == "https://www.google.com/travel/hotels?x"  # sem site próprio, usa o link da busca
    assert hs[0].oferta == "Ótima promoção"  # selo traduzido


def test_leitura_anuncios(monkeypatch):
    from app.services import anuncios, viagens

    capturado = {}

    def falso_get(url, params, timeout):
        capturado.update(params)
        # casos reais que apareceram no primeiro teste com a SerpApi
        return RespostaFalsa({"organic_results": [
            {"title": "Passagens por R$ 199", "link": "https://www.melhoresdestinos.com.br/promo-1", "snippet": "Só hoje", "source": "Melhores Destinos",
             "date": "há 2 dias"},
            {"title": "sem link"},
            {"title": "https://s.afilio.com.br/?id=64e6", "link": "https://s.afilio.com.br/?id=64e6",
             "snippet": "Não há nenhuma informação disponível para esta página."},
            {"title": "Turbo 20x vale a pena?", "link": "https://www.youtube.com/watch?v=Xb", "snippet": "milhas"},
            {"title": "Azul em promoção", "link": "https://www.passagensimperdiveis.com.br/azul", "snippet": "Voos a R$ 150"},
            {"title": "Application error: a client-side exception", "link": "https://www.melhoresdestinos.com.br/x"},
            {"title": "Voos baratos para Barreiras", "link": "https://tn.wego.com/en/flights/br", "snippet": "Ofertas"},
        ]})

    monkeypatch.setattr(viagens.requests, "get", falso_get)
    lista = anuncios.buscar_anuncios("promoção passagens", ultimos_dias=7,
                                     sites=["melhoresdestinos.com.br", "passagensimperdiveis.com.br"])
    assert capturado["tbs"] == "qdr:w" and "currency" not in capturado
    assert capturado["q"] == "promoção passagens (site:melhoresdestinos.com.br OR site:passagensimperdiveis.com.br)"
    assert [a.titulo for a in lista] == ["Passagens por R$ 199", "Azul em promoção"]
    assert lista[1].fonte == "passagensimperdiveis.com.br"


RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Melhores Destinos</title>
<item><title>LATAM: passagens para Recife a partir de R$ 389</title><link>https://md/1</link>
<description>&lt;p&gt;Ida e volta saindo de &lt;b&gt;Goiânia&lt;/b&gt;.&lt;/p&gt;</description>
<pubDate>Tue, 27 Oct 2026 10:00:00 -0300</pubDate></item>
<item><title>Resort all inclusive com 40% off</title><link>https://md/2</link>
<description>Pacote em Porto de Galinhas</description><pubDate>Tue, 27 Oct 2026 09:00:00 -0300</pubDate></item>
<item><title>Gol fecha acordo de codeshare com companhia do Chile</title><link>https://md/noticia</link>
<description>Voos da Sky ficam disponíveis</description><pubDate>Tue, 27 Oct 2026 08:00:00 -0300</pubDate></item>
<item><title>Passagens antigas</title><link>https://md/velho</link><pubDate>Mon, 01 Sep 2026 10:00:00 -0300</pubDate></item>
</channel></rss>"""

ATOM_FEED = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Blog Atom</title>
<entry><title>Voos baratos para Lisboa</title><link href="https://atom/1"/>
<summary>Promoção relâmpago</summary><updated>2026-10-27T12:00:00Z</updated></entry>
</feed>"""


class RespostaFeed:
    def __init__(self, conteudo):
        self.content = conteudo.encode("utf-8")

    def raise_for_status(self):
        pass


def test_feeds_rss_e_atom_filtrando_data_e_palavras(monkeypatch):
    from datetime import datetime, timezone

    from app.services import feeds

    paginas = {"https://md/feed": RSS, "https://atom/feed": ATOM_FEED}
    monkeypatch.setattr(feeds.requests, "get", lambda url, headers, timeout: RespostaFeed(paginas[url]))

    class Agora(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 27, 18, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(feeds, "datetime", Agora)
    todos = feeds.buscar_nos_feeds(["https://md/feed", "https://atom/feed"], ultimos_dias=2)
    # o post antigo e a notícia sem promoção ficam de fora
    assert [a.link for a in todos] == ["https://md/1", "https://md/2", "https://atom/1"]
    com_noticias = feeds.buscar_nos_feeds(["https://md/feed"], ultimos_dias=2, so_promocoes=False)
    assert "https://md/noticia" in [a.link for a in com_noticias]
    assert todos[0].fonte == "Melhores Destinos" and todos[0].resumo == "Ida e volta saindo de Goiânia."
    assert todos[0].data == "27/10 10:00"

    so_voos = feeds.buscar_nos_feeds(["https://md/feed", "https://atom/feed"], palavras=["passagens", "voos"])
    assert [a.link for a in so_voos] == ["https://md/1", "https://atom/1"]


def test_feed_com_erro_nao_derruba_os_outros(monkeypatch):
    from app.services import feeds

    def get(url, headers, timeout):
        if "quebrado" in url:
            raise feeds.requests.ConnectionError("fora do ar")
        return RespostaFeed(ATOM_FEED)

    monkeypatch.setattr(feeds.requests, "get", get)
    assert len(feeds.buscar_nos_feeds(["https://quebrado/feed", "https://atom/feed"], ultimos_dias=36500)) == 1


def test_anuncios_por_feed_nao_gastam_busca(monkeypatch, isolar):
    monkeypatch.setattr(monitor, "buscar_nos_feeds", lambda feeds, palavras, dias, so_promo: [
        Anuncio(titulo="Passagens para Recife por R$ 389", link="https://md/1", fonte="Melhores Destinos", data="27/10 10:00")])
    cfg = monitor.Monitoramento(anuncios=[{"nome": "Passagens em promoção", "feeds": ["https://md/feed"]}])
    assert cfg.total_buscas() == 0
    monitor.executar(cfg, hoje=HOJE)
    assert "Passagens em promoção" in isolar[0] and "Recife por R$ 389" in isolar[0]
    with pytest.raises(ValueError):
        monitor.ItemAnuncio(nome="sem fonte")


def test_monitoramento_somente_rss_nao_exige_serpapi(tmp_path, monkeypatch, caplog):
    caplog.set_level("INFO")
    arquivo = tmp_path / "m.yml"
    arquivo.write_text(
        "anuncios:\n  - nome: Ofertas Netshoes\n"
        "    feeds: [https://exemplo.test/feed.xml]\n"
        "    palavras: [netshoes]\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MONITORAMENTO", str(arquivo))
    monkeypatch.setattr(settings, "serpapi_key", "")
    monkeypatch.setattr(settings, "telegram_bot_token", "token-teste")
    monkeypatch.setattr(settings, "telegram_chat_id", "@canal-teste")
    monkeypatch.setattr(monitor, "executar", lambda cfg, simular: {"postados": 0, "repetidos": 0, "erros": 0})
    assert monitor.main() == 0
    assert "0 busca(s) da SerpApi" in caplog.text


def test_monitoramento_com_busca_paga_sem_serpapi_falha(tmp_path, monkeypatch, caplog):
    arquivo = tmp_path / "m.yml"
    arquivo.write_text("produtos:\n  - termo: tênis\n", encoding="utf-8")
    monkeypatch.setenv("MONITORAMENTO", str(arquivo))
    monkeypatch.setattr(settings, "serpapi_key", "")
    monkeypatch.setattr(settings, "telegram_bot_token", "token-teste")
    monkeypatch.setattr(settings, "telegram_chat_id", "@canal-teste")
    assert monitor.main() == 1
    assert "dependem dela" in caplog.text