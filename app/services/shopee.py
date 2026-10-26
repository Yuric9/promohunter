import hashlib
import json
import time
from typing import List

import requests

from app.config import settings
from app.models import Produto

AFILIADOS_URL = "https://open-api.affiliate.shopee.com.br/graphql"
SITE_URL = "https://shopee.com.br/api/v4/search/search_items"

CAMPOS = "itemId productName priceMin priceDiscountRate sales ratingStar imageUrl shopName productLink offerLink"


def buscar_shopee(termo: str, limite: int = 10) -> List[Produto]:
    """Busca na Shopee. Usa a API de Afiliados se as chaves estiverem no .env."""
    if settings.shopee_app_id and settings.shopee_secret:
        return buscar_afiliados(termo, limite)
    return buscar_site(termo, limite)


def cabecalho_assinado(corpo: str, timestamp: int = None) -> dict:
    """Assinatura exigida pela API: SHA256(AppID + timestamp + corpo + Secret)."""
    timestamp = timestamp or int(time.time())
    base = f"{settings.shopee_app_id}{timestamp}{corpo}{settings.shopee_secret}"
    assinatura = hashlib.sha256(base.encode("utf-8")).hexdigest()
    return {
        "Content-Type": "application/json",
        "Authorization": f"SHA256 Credential={settings.shopee_app_id}, Timestamp={timestamp}, Signature={assinatura}",
    }


def buscar_afiliados(termo: str, limite: int = 10) -> List[Produto]:
    # json.dumps gera uma string com aspas e escapes válidos também em GraphQL
    query = f"{{ productOfferV2(keyword: {json.dumps(termo)}, sortType: 1, page: 1, limit: {int(limite)}) {{ nodes {{ {CAMPOS} }} }} }}"
    corpo = json.dumps({"query": query})  # a assinatura precisa ser do texto exato enviado
    r = requests.post(AFILIADOS_URL, data=corpo.encode("utf-8"), headers=cabecalho_assinado(corpo), timeout=15)
    dados = r.json() if r.content else {}
    if dados.get("errors"):
        erro = dados["errors"][0]
        codigo = (erro.get("extensions") or {}).get("code", "")
        raise RuntimeError(f"API de Afiliados recusou ({codigo}): {erro.get('message', 'erro desconhecido')}")
    r.raise_for_status()

    produtos = []
    for n in ((dados.get("data") or {}).get("productOfferV2") or {}).get("nodes") or []:
        preco = float(n.get("priceMin") or 0)
        desconto = int(n.get("priceDiscountRate") or 0)
        # A API não manda o preço antigo; ele é calculado a partir do % de desconto.
        original = round(preco / (1 - desconto / 100), 2) if 0 < desconto < 100 else None
        produtos.append(Produto(
            titulo=n.get("productName", ""),
            preco=preco,
            preco_original=original,
            desconto=desconto,
            link=n.get("offerLink") or n.get("productLink") or "",
            imagem=n.get("imageUrl") or "",
            plataforma="Shopee",
            avaliacao=float(n.get("ratingStar") or 0),
            vendidos=int(n.get("sales") or 0),
            loja=n.get("shopName") or "",
        ))
    return produtos


def buscar_site(termo: str, limite: int = 10) -> List[Produto]:
    """Busca direto no site (sem chaves). A Shopee costuma bloquear esse acesso."""
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://shopee.com.br/"}
    params = {"by": "relevancy", "keyword": termo, "limit": limite, "newest": 0, "order": "desc",
              "page_type": "search", "scenario": "PAGE_GLOBAL_SEARCH", "version": 2}
    r = requests.get(SITE_URL, params=params, headers=headers, timeout=15)
    if r.status_code in (403, 418, 429):
        raise RuntimeError(f"Shopee bloqueou a requisição ({r.status_code}). "
                           "Coloque SHOPEE_APP_ID e SHOPEE_SECRET da API de Afiliados nas Configurações.")
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
