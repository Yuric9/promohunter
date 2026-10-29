"""
Histórico de preços: guarda o menor preço de cada produto por dia, para conferir se a
"promoção" é de verdade.

Muita loja mostra um preço "de" inflado (ex.: "de R$ 899 por R$ 329" o ano inteiro). Por isso
o robô compara o preço de hoje com o que ELE MESMO viu nos últimos dias: só é promoção real
quando o preço caiu em relação à mediana do período.
"""
import json
import statistics
import threading
from datetime import date, timedelta
from typing import Dict, Iterable, Optional, Tuple

from app.config import settings

_lock = threading.Lock()
GUARDAR_DIAS = 45


def _arquivo():
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings.data_dir / "historico_precos.json"


def _ler() -> dict:
    arquivo = _arquivo()
    if not arquivo.exists():
        return {}
    try:
        with open(arquivo, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def registrar(produtos: Iterable, hoje: Optional[date] = None):
    """Anota o preço de hoje de cada produto (fica o menor do dia) e apaga o que passou de 45 dias."""
    hoje = hoje or date.today()
    dia, limite = hoje.isoformat(), (hoje - timedelta(days=GUARDAR_DIAS)).isoformat()
    with _lock:
        dados = _ler()
        for p in produtos:
            precos = dados.setdefault(p.link, {})
            precos[dia] = min(p.preco, precos.get(dia, p.preco))
        for link in list(dados):
            dados[link] = {d: v for d, v in dados[link].items() if d >= limite}
            if not dados[link]:
                del dados[link]
        with open(_arquivo(), "w", encoding="utf-8") as f:
            json.dump(dados, f, separators=(",", ":"))


def referencias(links: Iterable[str], hoje: Optional[date] = None, janela: int = 30) -> Dict[str, Tuple[Optional[float], int]]:
    """Para cada link: mediana dos preços dos dias anteriores (sem contar hoje) e quantos dias foram vistos."""
    hoje = hoje or date.today()
    inicio, dia = (hoje - timedelta(days=janela)).isoformat(), hoje.isoformat()
    with _lock:
        dados = _ler()
    resultado = {}
    for link in links:
        anteriores = [v for d, v in dados.get(link, {}).items() if inicio <= d < dia]
        resultado[link] = (statistics.median(anteriores), len(anteriores)) if anteriores else (None, 0)
    return resultado
