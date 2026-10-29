"""
Busca no Mercado Livre pela API oficial (não é programa de afiliados).

Desde 2025 a busca recusa quem não se identifica (403). Com um aplicativo grátis criado no portal
de desenvolvedores (ML_CLIENT_ID e ML_CLIENT_SECRET), o robô pede sozinho uma chave de acesso
(vale 6 horas) e a reaproveita enquanto não vence. ML_ACCESS_TOKEN continua aceito, se preferir.
"""
import logging
import time
from typing import List

import requests

from app.config import settings
from app.models import Produto

log = logging.getLogger(__name__)
TOKEN_URL = "https://api.mercadolibre.com/oauth/token"
_token = {"valor": "", "vence": 0.0}


def configurado() -> bool:
    return bool(settings.ml_access_token or (settings.ml_client_id and settings.ml_client_secret))


def obter_token() -> str:
    if settings.ml_access_token:
        return settings.ml_access_token
    if _token["valor"] and time.time() < _token["vence"]:
        return _token["valor"]
    r = requests.post(TOKEN_URL, data={
        "grant_type": "client_credentials",
        "client_id": settings.ml_client_id,
        "client_secret": settings.ml_client_secret,
    }, headers={"Accept": "application/json"}, timeout=20)
    dados = r.json() if r.content else {}
    if r.status_code != 200 or not dados.get("access_token"):
        raise RuntimeError(f"Mercado Livre não liberou a chave de acesso ({r.status_code}): "
                           f"{dados.get('message') or dados.get('error') or r.text[:200]}. "
                           "Confira ML_CLIENT_ID e ML_CLIENT_SECRET.")
    _token["valor"] = dados["access_token"]
    _token["vence"] = time.time() + int(dados.get("expires_in") or 21600) - 300
    return _token["valor"]


def buscar_mercadolivre(termo: str, limite: int = 50) -> List[Produto]:
    """Busca no Mercado Livre. Lança exceção se a API falhar (o chamador trata)."""
    url = f"https://api.mercadolibre.com/sites/{settings.ml_country}/search"
    headers = {"Authorization": f"Bearer {obter_token()}"} if configurado() else {}
    r = requests.get(url, params={"q": termo, "limit": min(limite, 50)}, headers=headers, timeout=20)
    if r.status_code in (401, 403):
        raise RuntimeError(f"Mercado Livre recusou a busca ({r.status_code}): {r.text[:200]}")
    r.raise_for_status()

    produtos = []
    for item in r.json().get("results", []):
        preco = float(item.get("price") or 0)
        original = item.get("original_price")
        original = float(original) if original else None
        desconto = int((1 - preco / original) * 100 + 0.5) if original and original > preco else 0
        if not preco or item.get("condition") == "used":  # só produtos novos
            continue
        produtos.append(Produto(
            titulo=item.get("title", ""),
            preco=preco,
            preco_original=original if desconto else None,
            desconto=desconto,
            link=item.get("permalink", ""),
            imagem=(item.get("thumbnail") or "").replace("-I.jpg", "-O.jpg"),
            plataforma="Mercado Livre",
            vendidos=item.get("sold_quantity") or 0,
            loja=(item.get("seller") or {}).get("nickname", "") or "Mercado Livre",
        ))
    return produtos
