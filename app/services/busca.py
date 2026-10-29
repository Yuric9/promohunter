import logging
from concurrent.futures import ThreadPoolExecutor

import requests

from app.config import settings
from app.models import ResultadoBusca
from app.services.google_shopping import buscar_google_shopping
from app.services import mercadolivre
from app.services.mercadolivre import buscar_mercadolivre
from app.services.shopee import buscar_shopee

log = logging.getLogger(__name__)

SEM_FONTES = ("Nenhuma fonte de busca configurada. Coloque SERPAPI_KEY (Google Shopping), "
              "as chaves da Shopee Afiliados ou ML_ACCESS_TOKEN nas Configurações.")


def fontes_ativas() -> dict:
    """Só usa as fontes que têm chave: sem chave, ML e Shopee sempre recusam (403)."""
    fontes = {}
    if settings.serpapi_key:
        fontes["Google Shopping"] = buscar_google_shopping
    if settings.shopee_app_id and settings.shopee_secret:
        fontes["Shopee"] = buscar_shopee
    if mercadolivre.configurado():
        fontes["Mercado Livre"] = buscar_mercadolivre
    return fontes


def buscar_todas(termo: str, limite: int = 10) -> ResultadoBusca:
    """Busca em todas as fontes ao mesmo tempo. Falhas viram avisos, não erros."""
    fontes = fontes_ativas()
    if not fontes:
        return ResultadoBusca(produtos=[], avisos=[SEM_FONTES])
    produtos, avisos = [], []
    with ThreadPoolExecutor(max_workers=len(fontes)) as pool:
        futuros = {nome: pool.submit(func, termo, limite) for nome, func in fontes.items()}
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
