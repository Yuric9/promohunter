"""
Robô de monitoramento: lê o monitoramento.yml, pesquisa tudo que está lá
(produtos, voos, hospedagens e anúncios de promoção), compara os preços e
posta as melhores ofertas no canal do Telegram.

Roda sozinho no GitHub Actions (.github/workflows/monitorar.yml), mas também
pode ser executado no computador:  python -m app.monitor
Com SIMULAR=true ele só mostra as mensagens, sem postar.
"""
import logging
import os
import sys
from datetime import date, timedelta
from html import escape
from pathlib import Path
from typing import List, Optional

import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator

from app.config import settings
from app.services.anuncios import buscar_anuncios
from app.services.comparador import comparar_termo
from app.services.google_shopping import buscar_google_shopping
from app.services.telegram import enviar_telegram, formatar_mensagem
from app.services.viagens import buscar_hospedagens, buscar_voos
from app.storage import ja_enviado, marcar_enviado

log = logging.getLogger("monitor")

ARQUIVO_PADRAO = Path("monitoramento.yml")
BUSCAS_GRATIS_MES = 250


# ---- Formato do monitoramento.yml ------------------------------------------------

class ItemProduto(BaseModel):
    termo: str
    preco_min: float = 0
    preco_max: Optional[float] = None
    desconto_min: int = 0


class ItemVoo(BaseModel):
    origem: str = Field(min_length=3, max_length=3)
    destino: str = Field(min_length=3, max_length=3)
    ida: Optional[date] = None
    ida_em_dias: Optional[int] = Field(None, ge=0)
    duracao_dias: int = Field(0, ge=0)  # 0 = só ida
    adultos: int = Field(1, ge=1)
    preco_max: Optional[float] = None
    so_preco_baixo: bool = False

    @model_validator(mode="after")
    def precisa_de_data(self):
        if self.ida is None and self.ida_em_dias is None:
            raise ValueError("informe 'ida' (data) ou 'ida_em_dias'")
        return self

    def datas(self, hoje: date):
        ida = self.ida or hoje + timedelta(days=self.ida_em_dias)
        volta = ida + timedelta(days=self.duracao_dias) if self.duracao_dias else None
        return ida, volta


class ItemHospedagem(BaseModel):
    local: str
    checkin: Optional[date] = None
    checkin_em_dias: Optional[int] = Field(None, ge=0)
    noites: int = Field(2, ge=1)
    adultos: int = Field(2, ge=1)
    diaria_max: Optional[float] = None
    nota_min: float = 0

    @model_validator(mode="after")
    def precisa_de_data(self):
        if self.checkin is None and self.checkin_em_dias is None:
            raise ValueError("informe 'checkin' (data) ou 'checkin_em_dias'")
        return self

    def datas(self, hoje: date):
        entrada = self.checkin or hoje + timedelta(days=self.checkin_em_dias)
        return entrada, entrada + timedelta(days=self.noites)


class ItemAnuncio(BaseModel):
    busca: str
    ultimos_dias: int = 7
    maximo_por_vez: int = Field(3, ge=1, le=10)


class Monitoramento(BaseModel):
    produtos: List[ItemProduto] = []
    voos: List[ItemVoo] = []
    hospedagens: List[ItemHospedagem] = []
    anuncios: List[ItemAnuncio] = []

    def total_buscas(self) -> int:
        return len(self.produtos) + len(self.voos) + len(self.hospedagens) + len(self.anuncios)


def carregar(arquivo: Path = ARQUIVO_PADRAO) -> Monitoramento:
    with open(arquivo, encoding="utf-8") as f:
        dados = yaml.safe_load(f) or {}
    return Monitoramento(**{k: v or [] for k, v in dados.items()})


# ---- Mensagens --------------------------------------------------------------------

def _brl(valor: float) -> str:
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _duracao(minutos: int) -> str:
    return f"{minutos // 60}h{minutos % 60:02d}" if minutos else ""


def _data(d: date) -> str:
    return d.strftime("%d/%m/%Y")


class Post(BaseModel):
    chave: str  # identifica a oferta para não postar repetido
    texto: str
    imagem: str = ""


def posts_produto(item: ItemProduto) -> List[Post]:
    produtos = buscar_google_shopping(item.termo)
    comp = comparar_termo(item.termo, produtos, item.desconto_min, item.preco_min, item.preco_max or float("inf"))
    if not comp:
        log.info("[produto] %s: nada dentro dos filtros", item.termo)
        return []
    return [Post(chave=comp.melhor_oferta.link, texto=formatar_mensagem(comp), imagem=comp.melhor_oferta.imagem)]


def posts_voo(item: ItemVoo, hoje: date) -> List[Post]:
    ida, volta = item.datas(hoje)
    rota = f"{item.origem.upper()} → {item.destino.upper()}"
    if ida < hoje:
        log.warning("[voo] %s: a data de ida %s já passou, atualize o monitoramento.yml", rota, ida)
        return []
    res = buscar_voos(item.origem, item.destino, ida, volta, item.adultos)
    if not res.voos:
        log.info("[voo] %s: nenhum voo encontrado", rota)
        return []
    melhor = res.voos[0]
    preco_baixo = res.nivel_preco == "low"
    dentro_do_preco = item.preco_max is None or melhor.preco <= item.preco_max
    if item.so_preco_baixo and not preco_baixo and not (item.preco_max and melhor.preco <= item.preco_max):
        log.info("[voo] %s: %s, preço %s (não está abaixo do normal)", rota, _brl(melhor.preco), res.nivel_preco or "?")
        return []
    if not item.so_preco_baixo and not dentro_do_preco:
        log.info("[voo] %s: mais barato %s, acima do limite %s", rota, _brl(melhor.preco), _brl(item.preco_max))
        return []

    selo = {"low": "🟢 Preço ABAIXO do normal", "typical": "🟡 Preço dentro do normal", "high": "🔴 Preço acima do normal"}
    linhas = [
        f"✈️ <b>PASSAGEM {escape(rota)}</b>",
        f"📅 Ida {_data(ida)}" + (f" · Volta {_data(volta)}" if volta else " · Só ida")
        + (f" · {item.adultos} adultos" if item.adultos > 1 else ""),
    ]
    if res.nivel_preco in selo:
        linhas.append(selo[res.nivel_preco])
    if res.faixa_tipica:
        linhas.append(f"📊 Normal para essa rota: {_brl(res.faixa_tipica[0])} a {_brl(res.faixa_tipica[1])}")
    linhas.append("")
    for i, voo in enumerate(res.voos[:3]):
        escalas = "direto" if voo.escalas == 0 else f"{voo.escalas} escala(s)"
        detalhe = " · ".join(x for x in [escape(voo.companhia), escalas, _duracao(voo.duracao_min)] if x)
        linhas.append(f"{'🏆' if i == 0 else '•'} <b>{_brl(voo.preco)}</b> — {detalhe}")
    if res.link:
        linhas += ["", f'🔗 <a href="{escape(res.link, quote=True)}">Ver no Google Voos</a>']
    chave = f"voo:{rota}:{ida}:{volta}:{melhor.preco:.0f}"
    return [Post(chave=chave, texto="\n".join(linhas))]


def posts_hospedagem(item: ItemHospedagem, hoje: date) -> List[Post]:
    entrada, saida = item.datas(hoje)
    if entrada < hoje:
        log.warning("[hospedagem] %s: o check-in %s já passou, atualize o monitoramento.yml", item.local, entrada)
        return []
    opcoes = [
        h for h in buscar_hospedagens(item.local, entrada, saida, item.adultos)
        if h.nota >= item.nota_min and (item.diaria_max is None or h.diaria <= item.diaria_max)
    ]
    if not opcoes:
        log.info("[hospedagem] %s: nada dentro dos filtros", item.local)
        return []
    # Promoções informadas pelo Google primeiro; depois a diária mais barata
    opcoes.sort(key=lambda h: (not h.oferta, h.diaria))
    melhor = opcoes[0]
    linhas = [
        f"🏨 <b>{escape(item.local.upper())}</b>",
        f"📅 {_data(entrada)} a {_data(saida)} · {item.noites} noite(s) · {item.adultos} adulto(s)",
        "",
    ]
    for i, h in enumerate(opcoes[:3]):
        nota = f" · ⭐ {h.nota:.1f}" if h.nota else ""
        total = f" (total {_brl(h.total)})" if h.total else ""
        oferta = f"\n   🔥 {escape(h.oferta)}" if h.oferta else ""
        nome = f'<a href="{escape(h.link, quote=True)}">{escape(h.nome)}</a>' if h.link else escape(h.nome)
        linhas.append(f"{'🏆' if i == 0 else '•'} {nome}{nota}\n   💰 <b>{_brl(h.diaria)}</b>/noite{total}{oferta}")
    chave = f"hotel:{item.local}:{entrada}:{melhor.nome}:{melhor.diaria:.0f}"
    return [Post(chave=chave, texto="\n".join(linhas), imagem=melhor.imagem)]


def posts_anuncio(item: ItemAnuncio) -> List[Post]:
    novos = [a for a in buscar_anuncios(item.busca, item.ultimos_dias) if not ja_enviado(a.link)][:item.maximo_por_vez]
    posts = []
    for a in novos:
        texto = (
            f"📢 <b>PROMOÇÃO ANUNCIADA</b> · {escape(item.busca)}\n\n"
            f"<b>{escape(a.titulo)}</b>\n"
            + (f"{escape(a.resumo)}\n" if a.resumo else "")
            + (f"🗓 {escape(a.data)} · " if a.data else "")
            + (f"{escape(a.fonte)}\n" if a.fonte else "\n")
            + f'\n🔗 <a href="{escape(a.link, quote=True)}">Abrir anúncio</a>'
        )
        posts.append(Post(chave=a.link, texto=texto))
    return posts


# ---- Execução --------------------------------------------------------------------

def executar(cfg: Monitoramento, simular: bool = False, hoje: Optional[date] = None) -> dict:
    hoje = hoje or date.today()
    resumo = {"postados": 0, "repetidos": 0, "erros": 0}
    tarefas = (
        [(f"produto '{i.termo}'", lambda i=i: posts_produto(i)) for i in cfg.produtos]
        + [(f"voo {i.origem}→{i.destino}", lambda i=i: posts_voo(i, hoje)) for i in cfg.voos]
        + [(f"hospedagem '{i.local}'", lambda i=i: posts_hospedagem(i, hoje)) for i in cfg.hospedagens]
        + [(f"anúncios '{i.busca}'", lambda i=i: posts_anuncio(i)) for i in cfg.anuncios]
    )
    for nome, tarefa in tarefas:
        try:
            posts = tarefa()
        except Exception as e:
            resumo["erros"] += 1
            log.error("❌ %s: %s", nome, e)
            continue
        for post in posts:
            if ja_enviado(post.chave):
                resumo["repetidos"] += 1
                log.info("↩️  %s: oferta já postada recentemente", nome)
                continue
            if simular:
                print(f"\n----- {nome} (simulação, não postado) -----\n{post.texto}\n")
                resumo["postados"] += 1
                continue
            envio = enviar_telegram(post.texto, post.imagem)
            if envio["ok"]:
                marcar_enviado(post.chave)
                resumo["postados"] += 1
                log.info("✅ %s: postado no Telegram", nome)
            else:
                resumo["erros"] += 1
                log.error("❌ %s: falha ao postar no Telegram: %s", nome, envio["erro"])
    return resumo


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    arquivo = Path(os.environ.get("MONITORAMENTO", ARQUIVO_PADRAO))
    simular = os.environ.get("SIMULAR", "").lower() in ("1", "true", "sim")
    try:
        cfg = carregar(arquivo)
    except FileNotFoundError:
        log.error("Arquivo %s não encontrado.", arquivo)
        return 1
    except yaml.YAMLError as e:
        log.error("O %s tem um erro de formatação (confira os espaços no começo das linhas):\n%s", arquivo, e)
        return 1
    except ValidationError as e:
        log.error("O %s tem um valor inválido:\n%s", arquivo, e)
        return 1

    if not settings.serpapi_key:
        log.error("Falta a chave SERPAPI_KEY (no GitHub: Settings → Secrets and variables → Actions).")
        return 1
    if not simular and not (settings.telegram_bot_token and settings.telegram_chat_id):
        log.error("Faltam TELEGRAM_BOT_TOKEN e/ou TELEGRAM_CHAT_ID (no GitHub: Settings → Secrets and variables → Actions).")
        return 1

    total = cfg.total_buscas()
    log.info("🔎 %d item(ns) para pesquisar = %d busca(s) da SerpApi nesta execução.", total, total)
    if total * 30 > BUSCAS_GRATIS_MES:
        log.warning("⚠️  Rodando 1x por dia, isso dá ~%d buscas/mês (o plano grátis tem %d).", total * 30, BUSCAS_GRATIS_MES)

    resumo = executar(cfg, simular)
    log.info("\nResumo: %(postados)d postado(s), %(repetidos)d repetido(s), %(erros)d erro(s).", resumo)
    return 1 if resumo["erros"] and resumo["erros"] == total else 0


if __name__ == "__main__":
    sys.exit(main())
