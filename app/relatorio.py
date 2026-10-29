"""
Relatório de status: o que o robô verificou em cada execução e o que decidiu.

- Toda execução no GitHub Actions ganha uma página de resumo (aba Actions → execução) com a lista
  completa: produto, preço, preço "de", histórico e a decisão.
- Uma vez por dia (ou quando pedido) vai um resumo com exemplos só para o dono, no Telegram
  (TELEGRAM_DONO = o número do seu usuário no Telegram; o canal não recebe).
"""
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Dict, List, Optional

from pydantic import BaseModel

BRASILIA = timezone(timedelta(hours=-3))
ICONES = {"postado": "📣", "aprovado": "✅", "aguardando": "⏳", "inflado": "❌", "rejeitado": "🚫"}
NOMES = {"postado": "postada(s) no canal", "aprovado": "promoção real (fica para a próxima)",
         "aguardando": "aguardando histórico", "inflado": "preço \"de\" inflado (sem queda real)",
         "rejeitado": "não passou na verificação"}


class Registro(BaseModel):
    categoria: str  # "loja", "passagem" ou "pousada"
    origem: str  # loja, blog ou destino
    titulo: str
    situacao: str  # chave de ICONES
    preco: Optional[float] = None
    preco_de: Optional[float] = None
    desconto: int = 0
    detalhe: str = ""
    link: str = ""
    chave: str = ""


class Loja(BaseModel):
    nome: str
    lidos: int
    com_desconto: int


registros: List[Registro] = []
lojas: List[Loja] = []


def limpar():
    registros.clear()
    lojas.clear()


def anotar(**dados):
    registros.append(Registro(**dados))


def loja(nome: str, lidos: int, com_desconto: int):
    lojas.append(Loja(nome=nome, lidos=lidos, com_desconto=com_desconto))


def postado(chave: str):
    for r in registros:
        if r.chave == chave:
            r.situacao = "postado"


def _brl(valor: Optional[float]) -> str:
    if valor is None:
        return "-"
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def contagem(categoria: Optional[str] = None) -> Dict[str, int]:
    total = {s: 0 for s in ICONES}
    for r in registros:
        if categoria is None or r.categoria == categoria:
            total[r.situacao] += 1
    return total


def _linha_contagem(categoria: str) -> str:
    c = contagem(categoria)
    return " · ".join(f"{ICONES[s]} {n} {NOMES[s]}" for s, n in c.items() if n) or "nada verificado"


def markdown(agora: Optional[datetime] = None) -> str:
    """Página de resumo do GitHub Actions (formato Markdown)."""
    agora = agora or datetime.now(BRASILIA)
    linhas = [f"# 📊 Status do PromoHunter — {agora:%d/%m %H:%M}", ""]
    if lojas:
        lidos = sum(l.lidos for l in lojas)
        linhas += [f"**Lojas:** {len(lojas)} buscas · {lidos} produtos lidos · "
                   f"{sum(l.com_desconto for l in lojas)} com o desconto mínimo", "",
                   _linha_contagem("loja"), ""]
    for categoria, titulo in (("passagem", "✈️ Passagens"), ("pousada", "🏨 Pousadas")):
        if any(r.categoria == categoria for r in registros):
            linhas += [f"**{titulo}:** {_linha_contagem(categoria)}", ""]
    linhas += ["| | Origem | Item | Preço | Preço \"de\" | Situação |", "|---|---|---|---|---|---|"]
    ordem = list(ICONES)
    for r in sorted(registros, key=lambda r: (ordem.index(r.situacao), r.categoria, r.origem)):
        titulo = r.titulo.replace("|", "/")[:80]
        if r.link:
            titulo = f"[{titulo}]({r.link})"
        linhas.append(f"| {ICONES[r.situacao]} | {r.origem} | {titulo} | {_brl(r.preco)} | "
                      f"{_brl(r.preco_de)}{f' ({r.desconto}%)' if r.desconto else ''} | {r.detalhe} |")
    if not registros:
        linhas.append("| | | Nada para verificar nesta execução | | | |")
    return "\n".join(linhas) + "\n"


def telegram(agora: Optional[datetime] = None, exemplos: int = 12) -> str:
    """Resumo curto com exemplos (cabe numa mensagem do Telegram)."""
    agora = agora or datetime.now(BRASILIA)
    partes = [f"📊 <b>Status do PromoHunter</b> — {agora:%d/%m %H:%M}", ""]
    if lojas:
        partes.append(f"🏬 <b>Lojas:</b> {len(lojas)} buscas · {sum(l.lidos for l in lojas)} produtos lidos · "
                      f"{sum(l.com_desconto for l in lojas)} com desconto mínimo")
        partes.append(escape(_linha_contagem("loja")))
    for categoria, titulo in (("passagem", "✈️ <b>Passagens:</b>"), ("pousada", "🏨 <b>Pousadas:</b>")):
        if any(r.categoria == categoria for r in registros):
            partes.append(f"{titulo} {escape(_linha_contagem(categoria))}")
    # exemplos: primeiro os que passaram, depois um de cada situação em cada origem
    ordem = list(ICONES)
    escolhidos, vistos = [], set()
    for r in sorted(registros, key=lambda r: ordem.index(r.situacao)):
        if len(escolhidos) >= exemplos:
            break
        if r.situacao in ("postado", "aprovado") or (r.origem, r.situacao) not in vistos:
            escolhidos.append(r)
            vistos.add((r.origem, r.situacao))
    if escolhidos:
        partes += ["", "<b>Exemplos do que foi verificado:</b>"]
        for r in escolhidos:
            preco = f" — {_brl(r.preco)}" if r.preco is not None else ""
            de = f" (de {_brl(r.preco_de)}, {r.desconto}% OFF)" if r.preco_de else ""
            partes.append(f"{ICONES[r.situacao]} {escape(r.titulo[:60])}{preco}{de}\n"
                          f"     <i>{escape(r.origem)} · {escape(r.detalhe)}</i>")
    partes += ["", "Lista completa: GitHub → Actions → Monitorar promoções → última execução."]
    texto = "\n".join(partes)
    return texto if len(texto) <= 4000 else texto[:3990] + "…"
