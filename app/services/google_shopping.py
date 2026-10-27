import re
from typing import List, Optional

import requests

from app.config import settings
from app.models import Produto

SERPAPI_URL = "https://serpapi.com/search.json"


def _preco(valor) -> Optional[float]:
    """Aceita número ou texto como 'R$ 1.299,90' e devolve 1299.9."""
    if isinstance(valor, (int, float)):
        return float(valor)
    if not valor:
        return None
    texto = re.sub(r"[^\d,\.]", "", str(valor))
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return None


def _desconto(preco: float, original: Optional[float], tag: str) -> int:
    if original and original > preco > 0:
        return int((1 - preco / original) * 100)
    achado = re.search(r"(\d{1,2})\s*%", tag or "")
    return int(achado.group(1)) if achado else 0


def buscar_google_shopping(termo: str, limite: int = 10) -> List[Produto]:
    """Busca em todas as lojas do Google Shopping Brasil (via SerpApi). Cada chamada gasta 1 busca do plano."""
    params = {
        "engine": "google_shopping",
        "q": termo,
        "gl": "br",
        "hl": "pt-br",
        "google_domain": "google.com.br",
        "api_key": settings.serpapi_key,
    }
    r = requests.get(SERPAPI_URL, params=params, timeout=30)
    dados = r.json() if r.content else {}
    if dados.get("error"):
        if "hasn't returned any results" in dados["error"]:
            return []
        raise RuntimeError(f"SerpApi: {dados['error']}")
    r.raise_for_status()

    produtos = []
    for item in (dados.get("shopping_results") or [])[:limite]:
        preco = _preco(item.get("extracted_price")) or _preco(item.get("price"))
        if not preco:
            continue
        original = _preco(item.get("extracted_old_price")) or _preco(item.get("old_price"))
        desconto = _desconto(preco, original, item.get("tag", ""))
        if not original and desconto:
            original = round(preco / (1 - desconto / 100), 2)
        produtos.append(Produto(
            titulo=item.get("title", ""),
            preco=preco,
            preco_original=original if original and original > preco else None,
            desconto=desconto,
            link=item.get("link") or item.get("product_link") or "",
            imagem=item.get("thumbnail") or "",
            plataforma="Google Shopping",
            avaliacao=float(item.get("rating") or 0),
            vendidos=int(item.get("reviews") or 0),
            loja=item.get("source") or "",
        ))
    return produtos
