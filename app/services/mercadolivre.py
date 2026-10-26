import logging
from typing import List

import requests

from app.config import settings
from app.models import Produto

log = logging.getLogger(__name__)


def buscar_mercadolivre(termo: str, limite: int = 10) -> List[Produto]:
    """Busca no Mercado Livre. Lança exceção se a API falhar (o chamador trata)."""
    url = f"https://api.mercadolibre.com/sites/{settings.ml_country}/search"
    headers = {}
    if settings.ml_access_token:
        headers["Authorization"] = f"Bearer {settings.ml_access_token}"
    r = requests.get(url, params={"q": termo, "limit": limite}, headers=headers, timeout=10)
    if r.status_code in (401, 403):
        raise RuntimeError(f"Mercado Livre recusou o acesso ({r.status_code}). Configure ML_ACCESS_TOKEN.")
    r.raise_for_status()

    produtos = []
    for item in r.json().get("results", []):
        preco = float(item.get("price") or 0)
        original = item.get("original_price")
        original = float(original) if original else None
        desconto = int((1 - preco / original) * 100) if original and original > preco else 0
        produtos.append(Produto(
            titulo=item.get("title", ""),
            preco=preco,
            preco_original=original if desconto else None,
            desconto=desconto,
            link=item.get("permalink", ""),
            imagem=(item.get("thumbnail") or "").replace("-I.jpg", "-O.jpg"),
            plataforma="Mercado Livre",
            vendidos=item.get("sold_quantity") or 0,
            loja=(item.get("seller") or {}).get("nickname", ""),
        ))
    return produtos
