"""
Confere no Google Voos se a passagem anunciada num blog é promoção de verdade.

O robô lê o post ("Passagens para Recife a partir de R$ 389 saindo de São Paulo"), descobre
origem, destino e preço e consulta o Google Voos (1 busca da SerpApi). Só é promoção quando o
preço do post está pelo menos 10% abaixo do que a rota custava há ~30 dias ou abaixo da faixa
de preço normal da rota.

Com uma origem fixa (ex.: GYN), o post só indica o DESTINO: o robô confere o preço saindo da sua
cidade (Goiânia → Recife) e só posta se essa rota estiver mais barata que o normal. Para não estourar o plano grátis, são no máximo VERIFICACOES_DIA
consultas por dia, e o resultado de cada post fica guardado (o mesmo post não gasta duas vezes).
"""
import json
import logging
import re
import threading
import time
import unicodedata
from datetime import date, timedelta
from html import escape
from typing import Optional

from pydantic import BaseModel

from app.config import settings
from app.interpretador import AEROPORTOS, NOMES, _aeroportos, _datas
from app.services.viagens import buscar_voos

log = logging.getLogger(__name__)
_lock = threading.Lock()
PRECO = re.compile(r"R\$\s*(\d{1,3}(?:\.\d{3})*(?:,\d{2})?|\d+(?:,\d{2})?)")
CODIGOS = {c for v in AEROPORTOS.values() for c in v.split(",")}
ORIGEM = re.compile(r"\b(?:saindo|partindo|decolando|embarcando|voando)\s+(?:de|do|da|desde)\s+", re.I)


class VooAnunciado(BaseModel):
    origem: str
    destino: str
    nome_origem: str
    nome_destino: str
    preco: Optional[float] = None  # preço anunciado no post (sem origem fixa)
    ida: date
    ida_e_volta: bool


def _brl(valor: float) -> str:
    return f"R$ {valor:,.0f}".replace(",", ".")


def nome_da_cidade(codigo: str) -> str:
    cidade = next((c for c, v in AEROPORTOS.items() if v.split(",")[0] == codigo.split(",")[0]), "")
    return NOMES.get(cidade, cidade.title()) or codigo


def extrair(texto: str, hoje: Optional[date] = None, origem_fixa: str = "") -> Optional[VooAnunciado]:
    """Origem, destino e preço do post. Com `origem_fixa`, basta o destino.
    None quando falta algo (aí não dá para conferir)."""
    hoje = hoje or date.today()
    sem_acento = "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
    preco = PRECO.search(sem_acento)
    # palavras de 3 letras em maiúsculas (GOL, OFF...) só contam se forem um aeroporto conhecido
    cidades = [c for c in _aeroportos(sem_acento) if c[1] != c[0] or c[0] in CODIGOS]
    # "saindo de São Paulo" marca a origem do post
    marca = ORIGEM.search(sem_acento)
    origem_do_post = next((c for c in cidades if marca and c[2] == marca.end()), None)
    futuras = [d for d in _datas(sem_acento.lower(), hoje) if d > hoje]
    ida = futuras[0] if futuras else hoje + timedelta(days=45)
    if origem_fixa:
        candidatos = [c for c in cidades if c is not origem_do_post and c[0] != origem_fixa] or \
                     [c for c in cidades if c[0] != origem_fixa]
        if not candidatos:
            return None
        destino = candidatos[0]
        return VooAnunciado(
            origem=origem_fixa, destino=destino[0], nome_origem=nome_da_cidade(origem_fixa), nome_destino=destino[1],
            ida=ida, ida_e_volta=not re.search(r"\b(so|somente|apenas)\s+ida\b", sem_acento, re.I),
        )
    if not preco or len(cidades) < 2:
        return None
    if origem_do_post:
        origem, destino = origem_do_post, next(c for c in cidades if c is not origem_do_post)
    else:
        origem, destino = cidades[0], cidades[1]
    if origem[0] == destino[0]:
        return None
    return VooAnunciado(
        origem=origem[0], destino=destino[0], nome_origem=origem[1], nome_destino=destino[1],
        preco=float(preco.group(1).replace(".", "").replace(",", ".")), ida=ida,
        ida_e_volta=bool(re.search(r"ida\s+e\s+volta", sem_acento, re.I)),
    )


def _arquivo():
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings.data_dir / "verificacoes_voos.json"


def _ler() -> dict:
    try:
        with open(_arquivo(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _salvar(dados: dict):
    with open(_arquivo(), "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False)


def _ha_30_dias(res) -> Optional[float]:
    if not res.historico:
        return None
    alvo = time.time() - 30 * 86400
    return min(res.historico, key=lambda e: abs(e[0] - alvo))[1]


def comparar(voo: VooAnunciado, res) -> Optional[str]:
    """Linha de verificação quando é promoção de verdade; None quando não é.
    Sem origem fixa compara o preço do post; com origem fixa, o menor preço que o Google achou na rota."""
    preco = voo.preco if voo.preco is not None else (res.voos[0].preco if res.voos else None)
    if preco is None:
        return None
    ha_30_dias = _ha_30_dias(res)
    abaixo_do_mes = ha_30_dias is not None and preco <= ha_30_dias * (1 - settings.queda_min / 100)
    abaixo_do_normal = bool(res.faixa_tipica) and preco < res.faixa_tipica[0]
    if not (abaixo_do_mes or abaixo_do_normal):
        return None
    partes = []
    if ha_30_dias is not None:
        partes.append(f"há 30 dias custava {_brl(ha_30_dias)}")
    if res.faixa_tipica:
        partes.append(f"normal para a rota: {_brl(res.faixa_tipica[0])} a {_brl(res.faixa_tipica[1])}")
    rota = f"{escape(voo.nome_origem)} → {escape(voo.nome_destino)}"
    if voo.preco is None:
        tipo = "ida e volta" if voo.ida_e_volta else "só ida"
        linha = (f"✈️ <b>Saindo de {escape(voo.nome_origem)}:</b> {rota} por <b>{_brl(preco)}</b> ({tipo}, "
                 f"ida {voo.ida.strftime('%d/%m')})\n✅ Verificado no Google Voos: " + "; ".join(partes))
        if res.link:
            linha += f'\n🔎 <a href="{escape(res.link, quote=True)}">Ver voos no Google</a>'
        return linha
    return f"✅ Verificado no Google Voos ({rota}, {_brl(preco)}): " + "; ".join(partes)


ultimo_motivo = {"texto": ""}  # por que o último post não passou (para o relatório de status)


def verificar(link: str, texto: str, hoje: Optional[date] = None, origem: str = "") -> Optional[str]:
    """Confere o post (uma vez só) e devolve a linha de verificação, ou None se não for promoção real
    ou não der para conferir."""
    hoje = hoje or date.today()
    with _lock:
        dados = _ler()
    chave = f"{link}|{origem}"
    if chave in dados.get("posts", {}):
        ultimo_motivo["texto"] = "já conferido antes: não estava abaixo do normal"
        return dados["posts"][chave]
    voo = extrair(texto, hoje, origem)
    if not voo:
        log.info("[verificação] %s: o post não diz %s; não dá para conferir", link,
                 "o destino" if origem else "origem, destino e preço")
        ultimo_motivo["texto"] = "o post não diz um destino com aeroporto conhecido"
        return None
    if not settings.serpapi_key:
        log.info("[verificação] sem SERPAPI_KEY: não dá para conferir no Google Voos")
        ultimo_motivo["texto"] = "sem SERPAPI_KEY"
        return None
    usados = dados.get("uso", {}).get(hoje.isoformat(), 0)
    if usados >= settings.verificacoes_dia:
        log.info("[verificação] limite de %d consultas por dia atingido; o post fica para amanhã", settings.verificacoes_dia)
        ultimo_motivo["texto"] = f"limite de {settings.verificacoes_dia} consultas por dia: fica para amanhã"
        return None
    volta = voo.ida + timedelta(days=7) if voo.ida_e_volta else None
    try:
        res = buscar_voos(voo.origem.split(",")[0], voo.destino.split(",")[0], voo.ida, volta)
        linha = comparar(voo, res)
    except Exception as e:
        log.warning("[verificação] %s: erro ao consultar o Google Voos (%s)", link, e)
        linha = None
    ultimo_motivo["texto"] = f"{voo.nome_origem} → {voo.nome_destino} não está abaixo do normal no Google Voos"
    log.info("[verificação] %s → %s: %s", voo.origem, voo.destino,
             "promoção real" if linha else "não é promoção de verdade")
    with _lock:
        dados = _ler()
        dados.setdefault("uso", {})[hoje.isoformat()] = dados.get("uso", {}).get(hoje.isoformat(), 0) + 1
        dados["uso"] = {d: n for d, n in dados["uso"].items() if d >= (hoje - timedelta(days=7)).isoformat()}
        dados.setdefault("posts", {})[chave] = linha
        dados["posts"] = dict(list(dados["posts"].items())[-500:])  # guarda só os 500 mais recentes
        _salvar(dados)
    return linha
