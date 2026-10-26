import logging
from concurrent.futures import ThreadPoolExecutor

import requests

from app.models import ResultadoBusca
from app.services.mercadolivre import buscar_mercadolivre
from app.services.shopee import buscar_shopee

log = logging.getLogger(__name__)

FONTES = {"Mercado Livre": buscar_mercadolivre, "Shopee": buscar_shopee}


def buscar_todas(termo: str, limite: int = 10) -> ResultadoBusca:
    """Busca em todas as plataformas ao mesmo tempo. Falhas viram avisos, não erros."""
    produtos, avisos = [], []
    with ThreadPoolExecutor(max_workers=len(FONTES)) as pool:
        futuros = {nome: pool.submit(func, termo, limite) for nome, func in FONTES.items()}
        for nome, futuro in futuros.items():
            try:
                produtos.extend(futuro.result())
            except Exception as e:
                log.warning("Falha ao buscar em %s: %s", nome, e)
                avisos.append(f"{nome}: {mensagem_amigavel(e)}")
    return ResultadoBusca(produtos=produtos, avisos=avisos)


def mensagem_amigavel(erro: Exception) -> str:
    if isinstance(erro, requests.Timeout):
        return "demorou demais para responder. Tente de novo."
    if isinstance(erro, requests.ConnectionError):
        return "não foi possível conectar. Verifique sua internet."
    return str(erro)
