from datetime import date

import pytest

from app import issues, monitor
from app.config import settings

HOJE = date(2026, 11, 1)

CORPO_VOO = """### Aeroporto de origem

gyn

### Aeroporto de destino

REC

### Data de ida

_No response_

### Ou: ida daqui a quantos dias

45

### Quantos dias de viagem

7

### Adultos

2

### Preço máximo (R$)

R$ 1.500

### Quando avisar

Abaixo do preço máximo OU quando o Google disser que está mais barato que o normal
"""

CORPO_HOTEL = """### Onde

pousadas em Pirenópolis

### Data de entrada

19/12/2026

### Ou: entrada daqui a quantos dias

_No response_

### Noites

2

### Adultos

2

### Diária máxima (R$)

350,00

### Nota mínima

4.0
"""

CORPO_BLOG = """### Nome

Nordeste

### Palavras

recife, salvador; fortaleza

### Blogs (feeds RSS)

https://www.melhoresdestinos.com.br/feed
https://outro.blog/feed

### Posts dos últimos quantos dias

3
"""


def test_formulario_de_voo():
    tipo, dados = issues.interpretar(CORPO_VOO)
    assert tipo == "voo"
    assert dados == {"origem": "gyn", "destino": "REC", "ida_em_dias": 45, "duracao_dias": 7, "adultos": 2,
                     "preco_max": 1500.0, "so_preco_baixo": True}
    item = monitor.ItemVoo(**dados, issue=7)
    assert item.datas(HOJE) == (date(2026, 12, 16), date(2026, 12, 23))


def test_formulario_de_hospedagem_e_blog():
    tipo, dados = issues.interpretar(CORPO_HOTEL)
    assert tipo == "hospedagem" and dados["checkin"] == "2026-12-19" and dados["diaria_max"] == 350.0
    assert "checkin_em_dias" not in dados and dados["nota_min"] == 4.0
    tipo, dados = issues.interpretar(CORPO_BLOG)
    assert tipo == "anuncio" and dados["palavras"] == ["recife", "salvador", "fortaleza"]
    assert dados["feeds"] == ["https://www.melhoresdestinos.com.br/feed", "https://outro.blog/feed"]


def test_issue_comum_nao_e_formulario():
    assert issues.interpretar("Achei um bug no painel") == (None, {})


@pytest.mark.parametrize("texto,valor", [("1500", 1500), ("1.500", 1500), ("1.500,90", 1500.9), ("R$ 349,9", 349.9), ("4.5", 4.5)])
def test_numeros_em_formato_brasileiro(texto, valor):
    assert issues._numero(texto) == valor


def test_html_do_telegram_vira_markdown():
    html = '🔥 <b>AIR FRYER</b>\n💰 De <s>R$ 459,90</s> por <b>R$ 289,90</b>\n🔗 <a href="https://x.com/a?b=1&amp;c=2">Ver oferta</a>'
    assert issues.html_para_markdown(html) == \
        "🔥 **AIR FRYER**\n💰 De ~~R$ 459,90~~ por **R$ 289,90**\n🔗 [Ver oferta](https://x.com/a?b=1&c=2)"


@pytest.fixture
def github_falso(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    estado = {"issues": [], "comentarios": []}
    monkeypatch.setattr(issues, "disponivel", lambda: True)
    monkeypatch.setattr(issues, "listar_issues_abertos", lambda: estado["issues"])
    monkeypatch.setattr(issues, "buscar_issue", lambda n: next(i for i in estado["issues"] if i["number"] == n))
    monkeypatch.setattr(issues, "comentar", lambda n, texto: estado["comentarios"].append((n, texto)))
    return estado


def test_formularios_entram_no_monitoramento_e_estranhos_sao_ignorados(github_falso, tmp_path):
    github_falso["issues"] = [
        {"number": 1, "body": CORPO_VOO, "author_association": "OWNER"},
        {"number": 2, "body": CORPO_HOTEL, "author_association": "NONE"},  # estranho
        {"number": 3, "body": "issue comum", "author_association": "OWNER"},
        {"number": 4, "body": CORPO_VOO.replace("REC", "RECIFE"), "author_association": "OWNER"},  # inválido
    ]
    cfg = monitor.carregar_tudo(tmp_path / "nao-existe.yml")
    assert [(v.destino, v.issue) for v in cfg.voos] == [("REC", 1)]
    assert cfg.hospedagens == []


def test_validar_issue_responde_com_resumo(github_falso):
    github_falso["issues"] = [{"number": 9, "body": CORPO_HOTEL, "author_association": "OWNER"}]
    monitor.validar_issue(9, hoje=HOJE)
    numero, texto = github_falso["comentarios"][0]
    assert numero == 9 and "✅ **Monitoramento ativo!**" in texto
    assert "pousadas em Pirenópolis" in texto and "19/12/2026 a 21/12/2026" in texto and "R$ 350,00" in texto


def test_validar_issue_explica_erro(github_falso):
    github_falso["issues"] = [{"number": 5, "body": CORPO_VOO.replace("R$ 1.500", "barato"), "author_association": "OWNER"}]
    monitor.validar_issue(5, hoje=HOJE)
    assert "❌" in github_falso["comentarios"][0][1] and "não é um número" in github_falso["comentarios"][0][1]


def test_validar_issue_ignora_estranhos(github_falso):
    github_falso["issues"] = [{"number": 6, "body": CORPO_HOTEL, "author_association": "NONE"}]
    monitor.validar_issue(6, hoje=HOJE)
    assert github_falso["comentarios"] == []


def test_oferta_postada_tambem_e_avisada_no_formulario(github_falso, monkeypatch):
    from app.models import Hospedagem

    monkeypatch.setattr(monitor, "enviar_telegram", lambda texto, imagem="": {"ok": True})
    monkeypatch.setattr(monitor, "buscar_hospedagens", lambda *a: [Hospedagem(nome="Pousada Boa", diaria=200, nota=4.6, link="https://b")])
    cfg = monitor.Monitoramento(hospedagens=[{"local": "pousadas em Pirenópolis", "checkin_em_dias": 10, "issue": 12}])
    monitor.executar(cfg, hoje=HOJE)
    numero, texto = github_falso["comentarios"][0]
    assert numero == 12 and "Nova oferta" in texto and "[Pousada Boa](https://b)" in texto


def test_formulario_de_produto_com_preco_minimo():
    corpo = "### Produto\n\niphone 17\n\n### Preço mínimo (R$)\n\n3.000\n\n### Preço máximo (R$)\n\n_No response_\n\n### Desconto mínimo (%)\n\n0\n"
    tipo, dados = issues.interpretar(corpo)
    assert tipo == "produto" and dados == {"termo": "iphone 17", "preco_min": 3000.0, "desconto_min": 0}
    assert "de R$ 3.000,00 até sem limite" in monitor.descrever(tipo, monitor.ItemProduto(**dados), HOJE)
