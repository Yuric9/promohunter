import time
from datetime import date

import pytest

from app import monitor, verificar_viagem
from app.config import settings
from app.models import Anuncio, Hospedagem, ResultadoVoos, Voo

HOJE = date(2026, 11, 1)
POST = "Passagens para Recife a partir de R$ 389 ida e volta saindo de São Paulo"


@pytest.fixture(autouse=True)
def isolar(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "serpapi_key", "chave-teste")
    monkeypatch.setattr(settings, "verificacoes_dia", 4)
    postados = []
    monkeypatch.setattr(monitor, "enviar_telegram", lambda texto, imagem="": postados.append(texto) or {"ok": True})
    return postados


def google(ha_30_dias, faixa=(450, 700)):
    agora = time.time()
    return ResultadoVoos(voos=[Voo(preco=600, companhia="GOL")], faixa_tipica=list(faixa),
                         historico=[[agora - 31 * 86400, ha_30_dias], [agora - 86400, 600]])


def test_extrai_origem_destino_preco_e_ida_e_volta():
    voo = verificar_viagem.extrair(POST, HOJE)
    assert (voo.origem, voo.destino, voo.preco, voo.ida_e_volta) == ("GRU,CGH,VCP", "REC", 389, True)
    voo = verificar_viagem.extrair("Voos de Goiânia para Salvador por R$ 1.249,90 em 10/12", HOJE)
    assert (voo.origem, voo.destino, voo.preco, voo.ida) == ("GYN", "SSA", 1249.90, date(2026, 12, 10))
    # sem origem ou sem preço não dá para conferir; "GOL" (companhia) não é aeroporto
    assert verificar_viagem.extrair("Passagens para Recife a partir de R$ 389 na GOL", HOJE) is None
    assert verificar_viagem.extrair("Dicas de Recife saindo de São Paulo", HOJE) is None


def test_preco_inflado_nao_passa_e_queda_real_passa():
    voo = verificar_viagem.extrair(POST, HOJE)
    # há 30 dias custava R$ 400 e a rota normalmente custa R$ 450 a 700... R$ 389 é só 3% abaixo do mês passado,
    # mas está abaixo da faixa normal: passa
    assert "normal para a rota: R$ 450 a R$ 700" in verificar_viagem.comparar(voo, google(400))
    # o blog diz "promoção", mas a rota já custava R$ 380 e o normal é R$ 350 a 500: não passa
    assert verificar_viagem.comparar(voo, google(380, faixa=(350, 500))) is None
    # caiu mais de 10% em relação a 30 dias atrás: passa
    assert "há 30 dias custava R$ 520" in verificar_viagem.comparar(voo, google(520, faixa=(350, 500)))


def test_verificacao_tem_limite_diario_e_nao_gasta_duas_vezes_no_mesmo_post(monkeypatch):
    chamadas = []
    monkeypatch.setattr(verificar_viagem, "buscar_voos", lambda *a: chamadas.append(a) or google(520))
    monkeypatch.setattr(settings, "verificacoes_dia", 2)
    assert verificar_viagem.verificar("https://blog/1", POST, HOJE)
    assert verificar_viagem.verificar("https://blog/1", POST, HOJE)  # já conferido: não gasta de novo
    assert verificar_viagem.verificar("https://blog/2", POST, HOJE)
    assert verificar_viagem.verificar("https://blog/3", POST, HOJE) is None  # limite do dia
    assert len(chamadas) == 2


def test_blog_so_posta_passagem_verificada(monkeypatch, isolar):
    posts = [Anuncio(titulo=POST, link="https://blog/recife"),
             Anuncio(titulo="Hotéis em Gramado com 30% OFF", link="https://blog/gramado")]
    monkeypatch.setattr(monitor, "buscar_nos_feeds", lambda *a: posts)
    monkeypatch.setattr(verificar_viagem, "buscar_voos", lambda *a: google(520, faixa=(350, 500)))
    cfg = monitor.Monitoramento(anuncios=[{"nome": "Brasil", "feeds": ["https://blog/feed"], "verificar_voos": True}])
    assert monitor.executar(cfg)["postados"] == 1
    assert "Recife" in isolar[0] and "✅ Verificado no Google Voos" in isolar[0]


def test_hotel_automatico_roda_1_vez_por_dia_e_so_com_selo_do_google(monkeypatch, isolar):
    buscas = []
    hoteis = [Hospedagem(nome="Pousada Sem Promo", diaria=300, nota=4.5),
              Hospedagem(nome="Resort Promo", diaria=450, nota=4.7, oferta="22% abaixo do normal")]
    monkeypatch.setattr(monitor, "buscar_hospedagens", lambda *a: buscas.append(a) or hoteis)
    cfg = monitor.Monitoramento(hospedagens=[{"local": "Porto de Galinhas", "checkin_em_dias": 30,
                                              "automatico": True, "so_ofertas_google": True}])
    gratis = cfg.so_gratis()
    assert len(gratis.hospedagens) == 1
    assert monitor.executar(gratis, hoje=HOJE)["postados"] == 1
    assert monitor.executar(gratis, hoje=HOJE)["postados"] == 0  # mesmo dia: não busca de novo
    assert len(buscas) == 1
    assert "Resort Promo" in isolar[0] and "Pousada Sem Promo" not in isolar[0]
    assert "Verificado no Google Hotéis" in isolar[0]
