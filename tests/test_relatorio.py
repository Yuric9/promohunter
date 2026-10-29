from datetime import date, datetime, timedelta

import pytest

from app import historico, monitor, relatorio
from app.config import settings
from app.models import Produto

AGORA = datetime(2026, 10, 30, 9, 0, tzinfo=relatorio.BRASILIA)


@pytest.fixture(autouse=True)
def isolar(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "historico_min_dias", 3)
    monkeypatch.setattr(settings, "telegram_dono", "")
    postados = []
    monkeypatch.setattr(monitor, "enviar_telegram", lambda texto, imagem="": postados.append(texto) or {"ok": True})
    return postados


def produto(nome, preco, link):
    return Produto(titulo=nome, preco=preco, preco_original=400, desconto=round((1 - preco / 400) * 100),
                   link=link, plataforma="VTEX")


def preparar(monkeypatch):
    hoje = date.today()
    # tênis A: sempre R$ 200 (preço "de" inflado) · tênis B: era R$ 250 e caiu para R$ 199 · tênis C: novo
    for d in range(1, 5):
        historico.registrar([produto("Tênis A", 200, "https://loja/a"), produto("Tênis B", 250, "https://loja/b")],
                            hoje - timedelta(days=d))
    agora = [produto("Tênis A", 200, "https://loja/a"), produto("Tênis B", 199, "https://loja/b"),
             produto("Tênis C", 150, "https://loja/c")]
    monkeypatch.setattr(monitor, "buscar_na_loja", lambda site, busca, plataforma: agora)
    return monitor.Monitoramento(lojas=[{"site": "https://www.loja.com.br", "busca": "tênis"}])


def test_relatorio_mostra_o_que_foi_verificado_e_a_decisao(monkeypatch, isolar):
    monitor.executar(preparar(monkeypatch))
    situacoes = {r.titulo: r.situacao for r in relatorio.registros}
    assert situacoes == {"Tênis A": "inflado", "Tênis B": "postado", "Tênis C": "aguardando"}
    md = relatorio.markdown(AGORA)
    assert "1 buscas · 3 produtos lidos · 3 com o desconto mínimo" in md
    assert "preço normal R$ 200,00 em 4 dias: sem queda real" in md
    assert "20% abaixo do normal (R$ 250,00)" in md and "0/3 dias de histórico" in md
    texto = relatorio.telegram(AGORA)
    assert "📣 1 postada(s) no canal" in texto and "❌ 1 preço" in texto and "⏳ 1 aguardando histórico" in texto
    assert texto.index("Tênis B") < texto.index("Tênis A")  # o que foi postado aparece primeiro


def test_status_vai_para_o_dono_uma_vez_por_dia_a_partir_das_8h(monkeypatch, isolar, tmp_path):
    enviados = []
    monkeypatch.setattr(monitor, "enviar_privado", lambda chat, texto: enviados.append((chat, texto)) or {"ok": True})
    monkeypatch.setattr(settings, "telegram_dono", "999")
    resumo = tmp_path / "resumo.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(resumo))
    monitor.executar(preparar(monkeypatch))
    monitor.publicar_relatorio(AGORA.replace(hour=6))  # cedo demais: só a página do GitHub
    assert enviados == [] and "Status do PromoHunter" in resumo.read_text(encoding="utf-8")
    monitor.publicar_relatorio(AGORA)
    monitor.publicar_relatorio(AGORA.replace(hour=15))  # já mandou hoje
    assert len(enviados) == 1 and enviados[0][0] == "999"
    monkeypatch.setenv("ENVIAR_STATUS", "true")  # pedido pelo Run workflow: manda de novo
    monitor.publicar_relatorio(AGORA.replace(hour=16))
    assert len(enviados) == 2
