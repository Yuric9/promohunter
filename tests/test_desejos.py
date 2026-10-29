import pytest

from app import bot, issues, monitor, relatorio
from app.config import settings
from app.models import Produto


@pytest.fixture(autouse=True)
def isolar(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "telegram_dono", "999")
    canal, privado = [], []
    monkeypatch.setattr(monitor, "enviar_telegram", lambda texto, imagem="": canal.append(texto) or {"ok": True})
    monkeypatch.setattr(monitor, "enviar_privado", lambda chat, texto: privado.append((chat, texto)) or {"ok": True})
    return canal, privado


def p(nome, preco, loja):
    return Produto(titulo=nome, preco=preco, link=f"https://{loja}/{preco}", plataforma="VTEX")


ESTOQUE = {
    "www.asics.com.br": [p("Tênis ASICS Novablast 5 Masculino", 449.9, "asics"),
                         p("Tênis ASICS Novablast 5 Infantil", 199.9, "asics")],
    "www.artwalk.com.br": [p("Tênis ASICS Novablast 5", 389.9, "artwalk")],
}


def test_desejo_procura_em_todas_as_lojas_e_avisa_no_privado_e_no_canal(monkeypatch, isolar):
    canal, privado = isolar
    monkeypatch.setattr(monitor, "buscar_na_loja", lambda host, termo, plataforma: ESTOQUE.get(host, []))
    cfg = monitor.Monitoramento(
        lojas=[{"site": "https://www.asics.com.br", "busca": "tênis"}, {"site": "https://www.artwalk.com.br"}],
        desejos=[{"termo": "asics novablast", "preco_max": 400, "excluir": ["infantil"]}])
    monkeypatch.setattr(monitor, "posts_loja", lambda item: [])
    assert monitor.executar(cfg)["postados"] == 1
    assert "LISTA DE DESEJOS:</b> asics novablast chegou em R$ 389,90" in canal[0] and "artwalk" in canal[0]
    assert privado[0][0] == "999" and privado[0][1].startswith("🔔 ⭐")
    assert any(r.categoria == "desejo" and r.situacao == "postado" for r in relatorio.registros)
    assert monitor.executar(cfg)["postados"] == 0  # o mesmo preço não avisa de novo


def test_desejo_acima_do_preco_nao_avisa_mas_aparece_no_relatorio(monkeypatch, isolar):
    canal, privado = isolar
    monkeypatch.setattr(monitor, "buscar_na_loja", lambda host, termo, plataforma: ESTOQUE.get(host, []))
    cfg = monitor.Monitoramento(lojas=[{"site": "https://www.asics.com.br"}],
                                desejos=[{"termo": "asics novablast", "preco_max": 300, "excluir": ["infantil"]}])
    monkeypatch.setattr(monitor, "posts_loja", lambda item: [])
    assert monitor.executar(cfg)["postados"] == 0 and canal == [] and privado == []
    r = next(r for r in relatorio.registros if r.categoria == "desejo")
    assert r.situacao == "rejeitado" and "seu alvo: R$ 300,00" in r.detalhe


def test_desejo_passa_na_frente_do_limite_de_posts(monkeypatch, isolar):
    canal, _ = isolar
    monkeypatch.setattr(monitor, "buscar_na_loja", lambda host, termo, plataforma: ESTOQUE.get(host, []))
    oferta = monitor.Post(chave="loja-x", texto="oferta comum")
    monkeypatch.setattr(monitor, "posts_loja", lambda item: [oferta])
    cfg = monitor.Monitoramento(lojas=[{"site": "https://www.artwalk.com.br"}],
                                desejos=[{"termo": "asics novablast", "preco_max": 400}])
    monitor.executar(cfg, limite=1)
    assert "LISTA DE DESEJOS" in canal[0]


def test_formulario_e_comandos_do_telegram(monkeypatch):
    criados, fechados = [], []
    monkeypatch.setattr(issues, "disponivel", lambda: True)
    monkeypatch.setattr(issues, "criar_issue", lambda titulo, corpo: criados.append((titulo, corpo)) or {"number": 21})
    monkeypatch.setattr(issues, "fechar_issue", lambda numero, comentario="": fechados.append(numero))
    resposta = bot.comando_desejo("/quero tênis asics novablast até R$ 400 sem infantil, feminino")
    assert "Anotado (nº 21)" in resposta and "R$ 400,00 ou menos" in resposta
    titulo, corpo = criados[0]
    tipo, dados = issues.interpretar(corpo)
    assert tipo == "desejo" and dados == {"termo": "tênis asics novablast", "preco_max": 400.0,
                                          "excluir": ["infantil", "feminino"]}
    abertos = [{"number": 21, "body": corpo, "author_association": "OWNER"},
               {"number": 3, "body": "### Produto\n\nair fryer", "author_association": "OWNER"}]
    monkeypatch.setattr(issues, "listar_issues_abertos", lambda: abertos)
    lista = bot.comando_desejo("/lista")
    assert "<b>21</b>. tênis asics novablast — até R$ 400,00" in lista and "air fryer" not in lista
    assert "Pronto" in bot.comando_desejo("/remover 21") and fechados == [21]
    assert "Não achei" in bot.comando_desejo("/remover 3")  # o formulário de produto não é desejo
    assert "preço máximo" in bot.comando_desejo("/quero tênis asics")
