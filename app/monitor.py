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
import re
import sys
from datetime import date, timedelta
from html import escape
from pathlib import Path
from typing import List, Optional

import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator

from app import issues
from app.config import settings
from app.services.anuncios import buscar_anuncios
from app.services.feeds import buscar_nos_feeds
from app.services.comparador import comparar_termo
from app.services.google_shopping import buscar_google_shopping
from app.services.telegram import enviar_telegram
from app.services.viagens import buscar_hospedagens, buscar_voos
from app.storage import ja_enviado, marcar_enviado

log = logging.getLogger("monitor")

ARQUIVO_PADRAO = Path("monitoramento.yml")
BUSCAS_GRATIS_MES = 250


# ---- Formato do monitoramento.yml ------------------------------------------------

class Item(BaseModel):
    issue: Optional[int] = None  # número do formulário no GitHub, quando veio de lá


class ItemProduto(Item):
    termo: str
    preco_min: float = 0
    preco_max: Optional[float] = None
    desconto_min: int = 0


class ItemVoo(Item):
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


class ItemHospedagem(Item):
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


class ItemAnuncio(Item):
    nome: str = ""
    feeds: List[str] = []  # feeds RSS de blogs de promoção (grátis, não gasta busca)
    palavras: List[str] = []  # só posts que mencionam alguma dessas palavras
    so_promocoes: bool = True  # descarta notícias sem preço/desconto/cupom
    busca: str = ""  # ou: busca no Google (gasta 1 busca)
    sites: List[str] = []
    ultimos_dias: int = 2
    maximo_por_vez: int = Field(3, ge=1, le=10)

    @model_validator(mode="after")
    def precisa_de_fonte(self):
        if not self.feeds and not self.busca:
            raise ValueError("informe 'feeds' ou 'busca'")
        return self

    @property
    def titulo(self) -> str:
        return self.nome or self.busca or "Promoções"


class Monitoramento(BaseModel):
    produtos: List[ItemProduto] = []
    voos: List[ItemVoo] = []
    hospedagens: List[ItemHospedagem] = []
    anuncios: List[ItemAnuncio] = []

    def total_buscas(self) -> int:
        """Buscas da SerpApi por execução (feeds RSS não contam)."""
        return len(self.produtos) + len(self.voos) + len(self.hospedagens) + sum(1 for a in self.anuncios if a.busca)


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


ACESSORIOS = re.compile(r"\b(capa|capinha|case|pel[ií]cula|cabo|carregador|suporte|adesivo|skin|bainha|"
                        r"protetor|pulseira|fone de ouvido|kit de limpeza)\b", re.I)


def sem_acessorios(termo: str, produtos: list) -> list:
    """Tira capinhas, películas etc., a não ser que a busca seja justamente por um acessório."""
    if ACESSORIOS.search(termo):
        return produtos
    return [p for p in produtos if not ACESSORIOS.search(p.titulo)]


def posts_produto(item: ItemProduto) -> List[Post]:
    produtos = sem_acessorios(item.termo, buscar_google_shopping(item.termo))
    comp = comparar_termo(item.termo, produtos, item.desconto_min, item.preco_min, item.preco_max or float("inf"))
    if not comp:
        mais_barato = min(produtos, key=lambda p: p.preco, default=None)
        detalhe = f"mais barato encontrado: {_brl(mais_barato.preco)} ({mais_barato.desconto}% off)" if mais_barato else "nenhum resultado"
        log.info("[produto] %s: nada dentro dos filtros — %s", item.termo, detalhe)
        return []
    m = comp.melhor_oferta
    titulo = m.titulo if len(m.titulo) <= 150 else m.titulo[:147] + "..."
    preco_anterior = _brl(m.preco_original) if m.preco_original else "não informado"
    texto = (
        f"📦 <b>{escape(titulo)}</b>\n"
        f"💰 Preço antigo: {preco_anterior}\n"
        f"🔥 Preço novo: {_brl(m.preco)}\n"
        f"📉 Desconto: {m.desconto}%\n"
        f'🔗 <a href="{escape(m.link, quote=True)}">Link direto</a>'
    )
    return [Post(chave=comp.melhor_oferta.link, texto=texto, imagem=comp.melhor_oferta.imagem)]


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
    texto = formatar_voos(rota, ida, volta, item.adultos, res)
    preco_baixo = res.nivel_preco == "low"
    dentro_do_preco = item.preco_max is None or melhor.preco <= item.preco_max
    if item.so_preco_baixo and not preco_baixo and not (item.preco_max and melhor.preco <= item.preco_max):
        log.info("[voo] %s: %s, preço %s (não está abaixo do normal)", rota, _brl(melhor.preco), res.nivel_preco or "?")
        return []
    if not item.so_preco_baixo and not dentro_do_preco:
        log.info("[voo] %s: mais barato %s, acima do limite %s", rota, _brl(melhor.preco), _brl(item.preco_max))
        return []

    chave = f"voo:{rota}:{ida}:{volta}:{melhor.preco:.0f}"
    return [Post(chave=chave, texto=texto)]


def formatar_voos(rota: str, ida: date, volta: Optional[date], adultos: int, res) -> str:
    selo = {"low": "🟢 Preço ABAIXO do normal", "typical": "🟡 Preço dentro do normal", "high": "🔴 Preço acima do normal"}
    linhas = [
        f"✈️ <b>PASSAGEM {escape(rota)}</b>",
        f"📅 Ida {_data(ida)}" + (f" · Volta {_data(volta)}" if volta else " · Só ida")
        + (f" · {adultos} adultos" if adultos > 1 else ""),
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
    return "\n".join(linhas)


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
    encontrados = buscar_nos_feeds(item.feeds, item.palavras, item.ultimos_dias, item.so_promocoes) if item.feeds else []
    if item.busca:
        encontrados += buscar_anuncios(item.busca, item.ultimos_dias, item.sites or None)
    novos = [a for a in encontrados if not ja_enviado(a.link)][:item.maximo_por_vez]
    if not novos:
        log.info("[anúncios] %s: nenhum anúncio novo (%d encontrados)", item.titulo, len(encontrados))
    posts = []
    for a in novos:
        texto = (
            f"📢 <b>PROMOÇÃO ANUNCIADA</b> · {escape(item.titulo)}\n\n"
            f"<b>{escape(a.titulo)}</b>\n"
            + (f"{escape(a.resumo)}\n" if a.resumo else "")
            + (f"🗓 {escape(a.data)} · " if a.data else "")
            + (f"{escape(a.fonte)}\n" if a.fonte else "\n")
            + f'\n🔗 <a href="{escape(a.link, quote=True)}">Abrir anúncio</a>'
        )
        posts.append(Post(chave=a.link, texto=texto))
    return posts


# ---- Formulários (issues do GitHub) --------------------------------------------

TIPOS = {
    "voo": (ItemVoo, "voos"),
    "hospedagem": (ItemHospedagem, "hospedagens"),
    "produto": (ItemProduto, "produtos"),
    "anuncio": (ItemAnuncio, "anuncios"),
}


def item_do_issue(issue: dict):
    """Converte um issue em item do monitor. Devolve (tipo, item) ou (None, None) se não for formulário."""
    tipo, dados = issues.interpretar(issue.get("body") or "")
    if not tipo:
        return None, None
    modelo, _ = TIPOS[tipo]
    return tipo, modelo(**dados, issue=issue["number"])


def adicionar_issues(cfg: Monitoramento) -> int:
    """Junta à configuração os formulários abertos no GitHub. Devolve quantos foram adicionados."""
    adicionados = 0
    for issue in issues.listar_issues_abertos():
        if not issues.autor_permitido(issue):
            continue  # repositório público: ignora formulários de estranhos
        try:
            tipo, item = item_do_issue(issue)
        except (ValidationError, ValueError) as e:
            log.warning("⚠️  Formulário #%s ignorado (preenchimento inválido): %s", issue["number"], e)
            continue
        if item:
            getattr(cfg, TIPOS[tipo][1]).append(item)
            adicionados += 1
    return adicionados


def descrever(tipo: str, item, hoje: date) -> str:
    """Resumo em português do que vai ser monitorado (para responder no formulário)."""
    def preco(v):
        return _brl(v) if v else "sem limite"
    if tipo == "voo":
        ida, volta = item.datas(hoje)
        quando = f"ida em {_data(ida)}" + (f", volta em {_data(volta)}" if volta else " (só ida)")
        if item.ida is None:
            quando += f" — sempre {item.ida_em_dias} dias à frente"
        aviso = "abaixo de " + preco(item.preco_max) + (" **ou** quando o Google indicar preço abaixo do normal" if item.so_preco_baixo else "")
        return f"✈️ Passagem **{item.origem.upper()} → {item.destino.upper()}**, {quando}, {item.adultos} adulto(s).\nAviso quando: {aviso}."
    if tipo == "hospedagem":
        entrada, saida = item.datas(hoje)
        return (f"🏨 **{item.local}**, de {_data(entrada)} a {_data(saida)} ({item.noites} noites, {item.adultos} adultos).\n"
                f"Diária até {preco(item.diaria_max)}, nota mínima {item.nota_min or 'qualquer'}.")
    if tipo == "produto":
        faixa = f"de {_brl(item.preco_min)} " if item.preco_min else ""
        return f"🛒 **{item.termo}**, {faixa}até {preco(item.preco_max)}, desconto mínimo de {item.desconto_min}%."
    return (f"📢 **{item.titulo}**: posts dos últimos {item.ultimos_dias} dias em {len(item.feeds)} blog(s)"
            + (f", com as palavras: {', '.join(item.palavras)}." if item.palavras else "."))


def validar_issue(numero: int, hoje: Optional[date] = None) -> int:
    """Chamado quando um formulário é criado/editado: confere e responde no próprio issue."""
    hoje = hoje or date.today()
    issue = issues.buscar_issue(numero)
    if not issues.autor_permitido(issue):
        log.info("Issue #%s de quem não é dono/colaborador: ignorado.", numero)
        return 0
    try:
        tipo, item = item_do_issue(issue)
    except (ValidationError, ValueError) as e:
        issues.comentar(numero, "❌ **Não consegui entender o formulário:**\n\n" + issues.erro_legivel(e)
                        + "\n\nClique em **⋯ → Edit** no topo deste issue, corrija e salve. Eu confiro de novo.")
        return 0
    if not item:
        return 0  # issue comum, não é formulário do PromoHunter
    cfg = carregar_tudo()
    total = cfg.total_buscas()
    custo = "Este item **não gasta** buscas da SerpApi (lê os blogs direto)." if tipo == "anuncio" else \
        f"Com ele, o robô faz **{total} busca(s) por dia** (~{total * 30}/mês de {BUSCAS_GRATIS_MES} grátis)."
    if total * 30 > BUSCAS_GRATIS_MES:
        custo += " ⚠️ **Passa do plano grátis**: feche algum formulário que você não precisa mais."
    issues.comentar(numero, "✅ **Monitoramento ativo!**\n\n" + descrever(tipo, item, hoje)
                    + f"\n\n{custo}\n\nO robô pesquisa todo dia às 08:17 e avisa aqui e no canal quando encontrar "
                    "uma oferta. Para **parar**, feche este issue (botão *Close issue*).")
    return 0


def carregar_tudo(arquivo: Path = ARQUIVO_PADRAO) -> Monitoramento:
    """monitoramento.yml + formulários abertos no GitHub (quando rodando no GitHub Actions)."""
    cfg = carregar(arquivo) if arquivo.exists() else Monitoramento()
    if issues.disponivel():
        n = adicionar_issues(cfg)
        log.info("📝 %d formulário(s) aberto(s) no GitHub incluído(s).", n)
    return cfg


# ---- Execução --------------------------------------------------------------------

def executar(cfg: Monitoramento, simular: bool = False, hoje: Optional[date] = None) -> dict:
    hoje = hoje or date.today()
    resumo = {"postados": 0, "repetidos": 0, "erros": 0}
    tarefas = (
        [(f"produto '{i.termo}'", i, lambda i=i: posts_produto(i)) for i in cfg.produtos]
        + [(f"voo {i.origem}→{i.destino}", i, lambda i=i: posts_voo(i, hoje)) for i in cfg.voos]
        + [(f"hospedagem '{i.local}'", i, lambda i=i: posts_hospedagem(i, hoje)) for i in cfg.hospedagens]
        + [(f"anúncios '{i.titulo}'", i, lambda i=i: posts_anuncio(i)) for i in cfg.anuncios]
    )
    for nome, item, tarefa in tarefas:
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
                log.info("\n----- %s (simulação, não postado) -----\n%s\n", nome, post.texto)
                resumo["postados"] += 1
                continue
            envio = enviar_telegram(post.texto, post.imagem)
            if envio["ok"]:
                marcar_enviado(post.chave)
                resumo["postados"] += 1
                log.info("✅ %s: postado no Telegram", nome)
                if item.issue:
                    issues.comentar(item.issue, "🔔 **Nova oferta postada no canal:**\n\n" + issues.html_para_markdown(post.texto))
            else:
                resumo["erros"] += 1
                log.error("❌ %s: falha ao postar no Telegram: %s", nome, envio["erro"])
    return resumo


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    arquivo = Path(os.environ.get("MONITORAMENTO", ARQUIVO_PADRAO))
    simular = os.environ.get("SIMULAR", "").lower() in ("1", "true", "sim")
    if os.environ.get("VALIDAR_ISSUE"):
        return validar_issue(int(os.environ["VALIDAR_ISSUE"]))
    try:
        cfg = carregar_tudo(arquivo)
    except FileNotFoundError:
        log.error("Arquivo %s não encontrado.", arquivo)
        return 1
    except yaml.YAMLError as e:
        log.error("O %s tem um erro de formatação (confira os espaços no começo das linhas):\n%s", arquivo, e)
        return 1
    except ValidationError as e:
        log.error("O %s tem um valor inválido:\n%s", arquivo, e)
        return 1

    total = cfg.total_buscas()
    if total and not settings.serpapi_key:
        log.error("Falta a chave SERPAPI_KEY: este monitoramento tem %d busca(s) que dependem dela.", total)
        return 1
    tem_itens = bool(cfg.produtos or cfg.voos or cfg.hospedagens or cfg.anuncios)
    if tem_itens and not simular and not (settings.telegram_bot_token and settings.telegram_chat_id):
        log.error("Faltam TELEGRAM_BOT_TOKEN e/ou TELEGRAM_CHAT_ID (no GitHub: Settings → Secrets and variables → Actions).")
        return 1

    log.info("🔎 %d item(ns) para pesquisar = %d busca(s) da SerpApi nesta execução.", total, total)
    if total * 30 > BUSCAS_GRATIS_MES:
        log.warning("⚠️  Rodando 1x por dia, isso dá ~%d buscas/mês (o plano grátis tem %d).", total * 30, BUSCAS_GRATIS_MES)

    resumo = executar(cfg, simular)
    verbo = "seria(m) postada(s) (simulação)" if simular else "postada(s)"
    log.info("\nResumo: %d oferta(s) %s, %d repetida(s), %d erro(s).", resumo["postados"], verbo, resumo["repetidos"], resumo["erros"])
    if resumo["erros"] and not resumo["postados"]:
        log.error("Nada foi postado e houve erros: veja as mensagens ❌ acima.")
        return 1  # marca a execução como falha no GitHub (que avisa por e-mail)
    return 0


if __name__ == "__main__":
    sys.exit(main())
