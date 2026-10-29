"""
Confere no Google Voos se a passagem anunciada num blog é promoção de verdade.

O robô lê o post ("Passagens para Recife a partir de R$ 389 saindo de São Paulo"), descobre
origem, destino e preço e consulta o Google Voos (1 busca da SerpApi). Só é promoção quando o
preço do post está pelo menos 10% abaixo do que a rota custava há ~30 dias ou abaixo da faixa
de preço normal da rota. Para não estourar o plano grátis, são no máximo VERIFICACOES_DIA
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
from app.interpretador import AEROPORTOS, _aeroportos, _datas
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
    preco: float
    ida: date
    ida_e_volta: bool


def _brl(valor: float) -> str:
    return f"R$ {valor:,.0f}".replace(",", ".")


def extrair(texto: str, hoje: Optional[date] = None) -> Optional[VooAnunciado]:
    """Origem, destino e preço do post. None quando falta algum deles (aí não dá para conferir)."""
    hoje = hoje or date.today()
    sem_acento = "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
    preco = PRECO.search(sem_acento)
    # palavras de 3 letras em maiúsculas (GOL, OFF...) só contam se forem um aeroporto conhecido
    cidades = [c for c in _aeroportos(sem_acento) if c[1] != c[0] or c[0] in CODIGOS]
    if not preco or len(cidades) < 2:
        return None
    # "saindo de São Paulo" marca a origem; senão vale a ordem "de X para Y"
    marca = ORIGEM.search(sem_acento)
    origem = next((c for c in cidades if marca and c[2] == marca.end()), None)
    if origem:
        destino = next(c for c in cidades if c is not origem)
    else:
        origem, destino = cidades[0], cidades[1]
    if origem[0] == destino[0]:
        return None
    valor = float(preco.group(1).replace(".", "").replace(",", "."))
    futuras = [d for d in _datas(sem_acento.lower(), hoje) if d > hoje]
    return VooAnunciado(
        origem=origem[0], destino=destino[0], nome_origem=origem[1], nome_destino=destino[1], preco=valor,
        ida=futuras[0] if futuras else hoje + timedelta(days=45),
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


def comparar(voo: VooAnunciado, res) -> Optional[str]:
    """Linha de verificação quando o preço do post é promoção de verdade; None quando não é."""
    ha_30_dias = None
    if res.historico:
        alvo = time.time() - 30 * 86400
        ha_30_dias = min(res.historico, key=lambda e: abs(e[0] - alvo))[1]
    abaixo_do_mes = ha_30_dias is not None and voo.preco <= ha_30_dias * (1 - settings.queda_min / 100)
    abaixo_do_normal = bool(res.faixa_tipica) and voo.preco < res.faixa_tipica[0]
    if not (abaixo_do_mes or abaixo_do_normal):
        return None
    partes = []
    if ha_30_dias is not None:
        partes.append(f"há 30 dias custava {_brl(ha_30_dias)}")
    if res.faixa_tipica:
        partes.append(f"normal para a rota: {_brl(res.faixa_tipica[0])} a {_brl(res.faixa_tipica[1])}")
    return (f"✅ Verificado no Google Voos ({escape(voo.nome_origem)} → {escape(voo.nome_destino)}, "
            f"{_brl(voo.preco)}): " + "; ".join(partes))


def verificar(link: str, texto: str, hoje: Optional[date] = None) -> Optional[str]:
    """Confere o post (uma vez só) e devolve a linha de verificação, ou None se não for promoção real
    ou não der para conferir."""
    hoje = hoje or date.today()
    with _lock:
        dados = _ler()
    if link in dados.get("posts", {}):
        return dados["posts"][link]
    voo = extrair(texto, hoje)
    if not voo:
        log.info("[verificação] %s: o post não diz origem, destino e preço; não dá para conferir", link)
        return None
    if not settings.serpapi_key:
        log.info("[verificação] sem SERPAPI_KEY: não dá para conferir no Google Voos")
        return None
    usados = dados.get("uso", {}).get(hoje.isoformat(), 0)
    if usados >= settings.verificacoes_dia:
        log.info("[verificação] limite de %d consultas por dia atingido; o post fica para amanhã", settings.verificacoes_dia)
        return None
    volta = voo.ida + timedelta(days=7) if voo.ida_e_volta else None
    try:
        res = buscar_voos(voo.origem.split(",")[0], voo.destino.split(",")[0], voo.ida, volta)
        linha = comparar(voo, res)
    except Exception as e:
        log.warning("[verificação] %s: erro ao consultar o Google Voos (%s)", link, e)
        linha = None
    log.info("[verificação] %s → %s: post %s, %s", voo.origem, voo.destino, _brl(voo.preco),
             "promoção real" if linha else "não é promoção de verdade")
    with _lock:
        dados = _ler()
        dados.setdefault("uso", {})[hoje.isoformat()] = dados.get("uso", {}).get(hoje.isoformat(), 0) + 1
        dados["uso"] = {d: n for d, n in dados["uso"].items() if d >= (hoje - timedelta(days=7)).isoformat()}
        dados.setdefault("posts", {})[link] = linha
        dados["posts"] = dict(list(dados["posts"].items())[-500:])  # guarda só os 500 mais recentes
        _salvar(dados)
    return linha
