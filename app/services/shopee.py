from typing import List

import requests

from app.models import Produto

SHOPEE = "https://shopee.com.br/api/v4/search/search_items"


def buscar_shopee(termo: str, limite: int = 10) -> List[Produto]:
    """Busca na Shopee. Lança exceção se a API falhar (o chamador trata)."""
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://shopee.com.br/"}
    params = {"by": "relevancy", "keyword": termo, "limit": limite, "newest": 0, "order": "desc",
              "page_type": "search", "scenario": "PAGE_GLOBAL_SEARCH", "version": 2}
    r = requests.get(SHOPEE, params=params, headers=headers, timeout=15)
    if r.status_code in (403, 418, 429):
        raise RuntimeError(f"Shopee bloqueou a requisição ({r.status_code}). Considere a API de afiliados.")
    r.raise_for_status()
    dados = r.json()
    if dados.get("items") is None and dados.get("error"):
        raise RuntimeError(f"Shopee retornou erro {dados.get('error')} (provável bloqueio anti-bot)")

    produtos = []
    for item in dados.get("items") or []:
        d = item.get("item_basic") or {}
        preco = (d.get("price") or 0) / 100000
        preco_before = (d.get("price_before_discount") or 0) / 100000
        produtos.append(Produto(
            titulo=d.get("name", ""),
            preco=preco,
            preco_original=preco_before if preco_before > preco else None,
            desconto=int(d.get("raw_discount") or 0),
            link=f"https://shopee.com.br/product/{d.get('shopid')}/{d.get('itemid')}",
            imagem=f"https://down-br.img.susercontent.com/file/{d['image']}" if d.get("image") else "",
            plataforma="Shopee",
            avaliacao=float((d.get("item_rating") or {}).get("rating_star") or 0),
            vendidos=d.get("sold") or 0,
        ))
    return produtos
