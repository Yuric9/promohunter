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
import time
from datetime import date, timedelta
from html import escape
from pathlib import Path
from typing import List, Optional, Tuple

import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator

from app import historico, issues, verificar_viagem
from app.config import settings
from app.services.anuncios import buscar_anuncios
from app.services.feeds import buscar_nos_feeds
from app.services.comparador import comparar_termo
from app.services.google_shopping import buscar_google_shopping
from app.services import mercadolivre
from app.services.lojas import buscar_na_loja, host_da_loja, tem_palavras
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
    desconto_min: int = 20


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
    criancas: List[int] = []  # idade de cada criança (bebê = 1), ex.: [1, 5, 12]
    diaria_max: Optional[float] = None
    nota_min: float = 0
    so_ofertas_google: bool = False  # só hotéis que o Google marca como abaixo do preço normal
    automatico: bool = False  # roda sozinho 1 vez por dia, mesmo na execução "só grátis" (gasta 1 busca/dia)

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
    excluir: List[str] = []  # descarta posts que mencionam alguma dessas (ex.: destinos internacionais)
    verificar_voos: bool = False  # só posta passagens conferidas no Google Voos (gasta SerpApi, com limite diário)
    origem: str = ""  # aeroporto de saída fixo (ex.: GYN): confere o preço da SUA cidade até o destino do post
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


class ItemLoja(Item):
    site: str  # endereço da loja, ex.: https://www.mizuno.com.br
    busca: str = ""  # opcional: só produtos com essas palavras (ex.: "tênis corrida")
    desconto_min: int = Field(20, ge=0, le=100)
    preco_min: float = 0
    preco_max: Optional[float] = None
    excluir: List[str] = []  # descarta produtos com essas palavras no nome (ex.: bebê, infantil)
    plataforma: Optional[str] = None  # "vtex" ou "shopify"; vazio = descobre sozinho
    maximo_por_vez: int = Field(5, ge=1, le=20)

    @property
    def titulo(self) -> str:
        return host_da_loja(self.site) + (f" ({self.busca})" if self.busca else "")


class Monitoramento(BaseModel):
    produtos: List[ItemProduto] = []
    voos: List[ItemVoo] = []
    hospedagens: List[ItemHospedagem] = []
    anuncios: List[ItemAnuncio] = []
    lojas: List[ItemLoja] = []

    def so_gratis(self) -> "Monitoramento":
        """Só o que não gasta SerpApi: lojas e feeds RSS (usado na execução automática)."""
        return Monitoramento(lojas=self.lojas, anuncios=[a for a in self.anuncios if not a.busca],
                             hospedagens=[h for h in self.hospedagens if h.automatico])

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


def formatar_oferta(p, verificado: Optional[Tuple[float, int]] = None) -> str:
    """Mensagem padrão do canal: nome, preço antigo, preço novo, desconto e link direto.
    Com `verificado` (mediana, dias), mostra também a comparação com o histórico de preços."""
    titulo = p.titulo if len(p.titulo) <= 150 else p.titulo[:147] + "..."
    preco_anterior = _brl(p.preco_original) if p.preco_original else "não informado"
    historico_txt = ""
    if verificado:
        mediana, dias = verificado
        historico_txt = (f"✅ Promoção verificada: {round((1 - p.preco / mediana) * 100)}% abaixo do preço "
                         f"normal ({_brl(mediana)} nos últimos {dias} dias)\n")
    return (
        f"📦 <b>{escape(titulo)}</b>\n"
        f"💰 Preço antigo: {preco_anterior}\n"
        f"🔥 Preço novo: {_brl(p.preco)}\n"
        f"📉 Desconto: {p.desconto}%\n"
        + historico_txt
        + f'🔗 <a href="{escape(p.link, quote=True)}">Link direto</a>'
    )


def posts_produto(item: ItemProduto, mais_baratas: bool = False) -> List[Post]:
    """Melhor oferta do produto. Com `mais_baratas` (usado na conversa com o robô), lista também
    as 3 opções mais baratas dentro dos filtros."""
    produtos = sem_acessorios(item.termo, buscar_google_shopping(item.termo))
    comp = comparar_termo(item.termo, produtos, item.desconto_min, item.preco_min, item.preco_max or float("inf"))
    if not comp:
        mais_barato = min(produtos, key=lambda p: p.preco, default=None)
        detalhe = f"mais barato encontrado: {_brl(mais_barato.preco)} ({mais_barato.desconto}% off)" if mais_barato else "nenhum resultado"
        log.info("[produto] %s: nada dentro dos filtros — %s", item.termo, detalhe)
        return []
    texto = formatar_oferta(comp.melhor_oferta)
    outras = sorted((p for p in comp.todas_ofertas if p.link != comp.melhor_oferta.link), key=lambda p: p.preco)[:3]
    if mais_baratas and outras:
        linhas = []
        for p in outras:
            titulo = p.titulo if len(p.titulo) <= 60 else p.titulo[:57] + "..."
            loja = f" · {escape(p.loja)}" if p.loja else ""
            linhas.append(f'• <b>{_brl(p.preco)}</b> — <a href="{escape(p.link, quote=True)}">{escape(titulo)}</a>{loja}')
        texto += "\n\n💸 <b>Mais baratas encontradas:</b>\n" + "\n".join(linhas)
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
    if item.automatico:
        chave_dia = f"hotel-dia:{item.local}:{hoje}"
        if ja_enviado(chave_dia):
            log.info("[hospedagem] %s: já conferido hoje (1 busca por dia)", item.local)
            return []
        marcar_enviado(chave_dia)
    opcoes = [
        h for h in buscar_hospedagens(item.local, entrada, saida, item.adultos, item.criancas)
        if h.nota >= item.nota_min and (item.diaria_max is None or h.diaria <= item.diaria_max)
        and (h.oferta or not item.so_ofertas_google)
    ]
    if not opcoes:
        log.info("[hospedagem] %s: nada dentro dos filtros", item.local)
        return []
    # Promoções informadas pelo Google primeiro; depois a diária mais barata
    opcoes.sort(key=lambda h: (not h.oferta, h.diaria))
    melhor = opcoes[0]
    linhas = [
        f"🏨 <b>{escape(item.local.upper())}</b>",
        f"📅 {_data(entrada)} a {_data(saida)} · {item.noites} noite(s) · {item.adultos} adulto(s)"
        + (f" + {len(item.criancas)} criança(s)" if item.criancas else ""),
    ]
    if item.so_ofertas_google:
        linhas.append("✅ Verificado no Google Hotéis: diária abaixo do preço normal de cada hotel")
    linhas.append("")
    for i, h in enumerate(opcoes[:3]):
        nota = f" · ⭐ {h.nota:.1f}" if h.nota else ""
        total = f" (total {_brl(h.total)})" if h.total else ""
        oferta = f"\n   🔥 {escape(h.oferta)}" if h.oferta else ""
        nome = f'<a href="{escape(h.link, quote=True)}">{escape(h.nome)}</a>' if h.link else escape(h.nome)
        linhas.append(f"{'🏆' if i == 0 else '•'} {nome}{nota}\n   💰 <b>{_brl(h.diaria)}</b>/noite{total}{oferta}")
    chave = f"hotel:{item.local}:{entrada}:{melhor.nome}:{melhor.diaria:.0f}"
    return [Post(chave=chave, texto="\n".join(linhas), imagem=melhor.imagem)]


def _modelo(titulo: str) -> str:
    return titulo.rsplit(" - ", 1)[0].strip().lower()


def posts_loja(item: ItemLoja) -> List[Post]:
    """Ofertas lidas direto no site da loja, com desconto de pelo menos `desconto_min`%."""
    if "mercadolivre" in host_da_loja(item.site) and not mercadolivre.configurado():
        log.info("[loja] %s: falta ML_CLIENT_ID e ML_CLIENT_SECRET (aplicativo do Mercado Livre); pulando", item.titulo)
        return []
    produtos = buscar_na_loja(item.site, item.busca, item.plataforma)
    historico.registrar(produtos)
    if not item.busca:
        produtos = sem_acessorios("", produtos)
    ofertas = [p for p in produtos if p.desconto >= item.desconto_min
               and item.preco_min <= p.preco <= (item.preco_max or float("inf"))
               and not any(tem_palavras(p.titulo, palavra) for palavra in item.excluir)]
    ofertas.sort(key=lambda p: p.desconto, reverse=True)
    # o mesmo produto em outra cor/tamanho ("Camiseta X - Azul", "Camiseta X - Preta") conta uma vez só
    vistos = set()
    ofertas = [p for p in ofertas if not (_modelo(p.titulo) in vistos or vistos.add(_modelo(p.titulo)))]
    # Preço "de" inflado é comum: só vale se o preço caiu em relação ao que o robô viu nos dias anteriores
    verificadas, sem_historico = [], 0
    if settings.historico_min_dias:
        refs = historico.referencias(p.link for p in ofertas)
        for p in ofertas:
            mediana, dias = refs[p.link]
            if dias < settings.historico_min_dias:
                sem_historico += 1
            elif p.preco <= mediana * (1 - settings.queda_min / 100):
                verificadas.append((p, (mediana, dias)))
    else:
        verificadas = [(p, None) for p in ofertas]
    # o mesmo produto volta a ser postado se o preço cair de novo
    novas = [(p, v) for p, v in verificadas if not ja_enviado(f"{p.link}|{p.preco:.0f}")][:item.maximo_por_vez]
    log.info("[loja] %s: %d produto(s), %d com %d%%+ de desconto, %d com queda real de preço, "
             "%d ainda sem histórico, %d nova(s)", item.titulo, len(produtos), len(ofertas), item.desconto_min,
             len(verificadas), sem_historico, len(novas))
    return [Post(chave=f"{p.link}|{p.preco:.0f}", texto=formatar_oferta(p, v), imagem=p.imagem) for p, v in novas]


def posts_anuncio(item: ItemAnuncio) -> List[Post]:
    encontrados = buscar_nos_feeds(item.feeds, item.palavras, item.ultimos_dias, item.so_promocoes) if item.feeds else []
    if item.busca:
        encontrados += buscar_anuncios(item.busca, item.ultimos_dias, item.sites or None)
    if item.excluir:
        fora = [p.lower() for p in item.excluir]
        encontrados = [a for a in encontrados if not any(p in f"{a.titulo} {a.resumo}".lower() for p in fora)]
    novos = [a for a in encontrados if not ja_enviado(a.link)]
    verificacao = {}
    if item.verificar_voos:
        # só passa o que o Google Voos confirmar: preço abaixo do que custava há 30 dias ou da faixa normal
        conferidos = []
        for a in novos:
            if len(conferidos) >= item.maximo_por_vez:
                break
            linha = verificar_viagem.verificar(a.link, f"{a.titulo} {a.resumo}", origem=item.origem.upper())
            if linha:
                verificacao[a.link] = linha
                conferidos.append(a)
        novos = conferidos
    novos = novos[:item.maximo_por_vez]
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
            + (f"\n{verificacao[a.link]}\n" if a.link in verificacao else "")
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
    "loja": (ItemLoja, "lojas"),
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
    if tipo == "loja":
        faixa = f", preço até {preco(item.preco_max)}" if item.preco_max else ""
        return (f"🏬 **{host_da_loja(item.site)}**" + (f", produtos com “{item.busca}”" if item.busca else ", todos os produtos")
                + f", desconto a partir de {item.desconto_min}%{faixa}.")
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
    if tipo in ("anuncio", "loja"):
        custo = "Este item **não gasta** buscas da SerpApi (lê direto no site)."
        quando = "O robô confere **a cada 30 minutos**"
    else:
        custo = f"Cada vez que você rodar o monitor, ele faz **{total} busca(s)** da SerpApi ({BUSCAS_GRATIS_MES} grátis por mês)."
        quando = "Para economizar a SerpApi, este item **não roda sozinho**: rode em Actions → Monitorar promoções → Run workflow"
    issues.comentar(numero, "✅ **Monitoramento ativo!**\n\n" + descrever(tipo, item, hoje)
                    + f"\n\n{custo}\n\n{quando} e avisa aqui e no canal quando encontrar "
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

def executar(cfg: Monitoramento, simular: bool = False, hoje: Optional[date] = None,
             limite: Optional[int] = None, inicio: int = 0) -> dict:
    """Pesquisa tudo e posta. `limite` = máximo de posts nesta execução (o resto fica para a próxima).
    `inicio` gira a ordem dos itens, para que a cada execução outras lojas venham primeiro."""
    hoje = hoje or date.today()
    resumo = {"postados": 0, "repetidos": 0, "erros": 0}
    tarefas = (
        [(f"produto '{i.termo}'", i, lambda i=i: posts_produto(i)) for i in cfg.produtos]
        + [(f"voo {i.origem}→{i.destino}", i, lambda i=i: posts_voo(i, hoje)) for i in cfg.voos]
        + [(f"hospedagem '{i.local}'", i, lambda i=i: posts_hospedagem(i, hoje)) for i in cfg.hospedagens]
        + [(f"anúncios '{i.titulo}'", i, lambda i=i: posts_anuncio(i)) for i in cfg.anuncios]
        + [(f"loja {i.titulo}", i, lambda i=i: posts_loja(i)) for i in cfg.lojas]
    )
    # 1) pesquisa tudo
    resultados = []
    for nome, item, tarefa in tarefas:
        try:
            resultados.append((nome, item, tarefa()))
        except Exception as e:
            resumo["erros"] += 1
            log.error("❌ %s: %s", nome, e)
    if resultados:
        k = inicio % len(resultados)
        resultados = resultados[k:] + resultados[:k]
    # 2) posta intercalando: 1 oferta de cada item por rodada, para o limite não ficar só nos primeiros da lista
    rodadas = max((len(posts) for _, _, posts in resultados), default=0)
    fila = [(nome, item, posts[r]) for r in range(rodadas) for nome, item, posts in resultados if r < len(posts)]
    for nome, item, post in fila:
        if limite and resumo["postados"] >= limite:
            log.info("⏸️  Limite de %d post(s) por execução atingido: o restante fica para a próxima.", limite)
            break
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

    if os.environ.get("SO_GRATIS", "").lower() in ("1", "true", "sim"):
        cfg = cfg.so_gratis()
        log.info("💸 Execução automática: lojas e blogs (grátis), passagens conferidas no Google Voos (até %d por dia) "
                 "e hospedagens marcadas como automáticas (1 vez por dia).", settings.verificacoes_dia)
    total = cfg.total_buscas()
    if total and not settings.serpapi_key:
        log.error("Falta a chave SERPAPI_KEY: este monitoramento tem %d busca(s) que dependem dela.", total)
        return 1
    tem_itens = bool(cfg.produtos or cfg.voos or cfg.hospedagens or cfg.anuncios or cfg.lojas)
    if tem_itens and not simular and not (settings.telegram_bot_token and settings.telegram_chat_id):
        log.error("Faltam TELEGRAM_BOT_TOKEN e/ou TELEGRAM_CHAT_ID (no GitHub: Settings → Secrets and variables → Actions).")
        return 1

    log.info("🔎 %d item(ns) para pesquisar = %d busca(s) da SerpApi nesta execução.", total, total)
    if total * 30 > BUSCAS_GRATIS_MES:
        log.warning("⚠️  Rodando 1x por dia, isso dá ~%d buscas/mês (o plano grátis tem %d).", total * 30, BUSCAS_GRATIS_MES)

    resumo = executar(cfg, simular, limite=int(os.environ.get("MAXIMO_POSTS") or 0) or None,
                      inicio=int(time.time() // 1800))  # muda a cada meia hora
    verbo = "seria(m) postada(s) (simulação)" if simular else "postada(s)"
    log.info("\nResumo: %d oferta(s) %s, %d repetida(s), %d erro(s).", resumo["postados"], verbo, resumo["repetidos"], resumo["erros"])
    if resumo["erros"] and not resumo["postados"]:
        log.error("Nada foi postado e houve erros: veja as mensagens ❌ acima.")
        return 1  # marca a execução como falha no GitHub (que avisa por e-mail)
    return 0


if __name__ == "__main__":
    sys.exit(main())
