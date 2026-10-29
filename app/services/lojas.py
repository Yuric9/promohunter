"""
Leitura grátis das ofertas direto no site das lojas (não gasta busca da SerpApi).

Muitas lojas rodam numa plataforma pronta que tem uma API pública de produtos:
- VTEX:    /api/catalog_system/pub/products/search  → preço "de" (ListPrice) e "por" (Price)
- Shopify: /products.json                           → compare_at_price ("de") e price ("por")
O leitor certo é descoberto sozinho na primeira vez (ou informado em `plataforma`).
"""
import logging
import re
import unicodedata
from typing import List, Optional
from urllib.parse import quote, urlparse

import requests

from app.models import Produto

log = logging.getLogger(__name__)

CABECALHOS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/130.0 Safari/537.36",
    "Accept": "application/json",
}
PLATAFORMAS = ("vtex", "shopify")


class LojaNaoSuportada(Exception):
    pass


def host_da_loja(site: str) -> str:
    """'https://www.loja.com.br/ofertas' → 'www.loja.com.br'"""
    site = site.strip()
    return urlparse(site if "://" in site else "https://" + site).netloc.lower()


def nome_da_loja(host: str) -> str:
    partes = [p for p in host.split(".") if p not in ("www", "loja", "br", "com", "store")]
    return (partes[0] if partes else host).capitalize()


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return sem_acento.lower()


def tem_palavras(titulo: str, palavras: str) -> bool:
    """True se o título tem todas as palavras (sem ligar para acento, masculino/masculina, plural)."""
    titulo = _normalizar(titulo)
    for w in _normalizar(palavras).split():
        raiz = w[:-1] if len(w) > 4 and w[-1] in "aos" else w
        if raiz not in titulo:
            return False
    return True


def _desconto(preco: float, preco_original: Optional[float]) -> int:
    if not preco_original or preco_original <= preco:
        return 0
    return int((preco_original - preco) / preco_original * 100 + 0.5)


def _get(url: str):
    r = requests.get(url, headers=CABECALHOS, timeout=25)
    if r.status_code not in (200, 206):
        raise LojaNaoSuportada(f"HTTP {r.status_code}")
    return r.json()


# ---- VTEX ----------------------------------------------------------------------------

def produtos_vtex(dados: list, host: str) -> List[Produto]:
    produtos = []
    for p in dados:
        for sku in p.get("items") or []:
            ofertas = [s.get("commertialOffer") or {} for s in sku.get("sellers") or []]
            oferta = next((o for o in ofertas if o.get("AvailableQuantity", 0) > 0 and o.get("Price")), None)
            if not oferta:
                continue
            preco, de = float(oferta["Price"]), float(oferta.get("ListPrice") or 0) or None
            imagens = sku.get("images") or []
            link = p.get("link") or f"https://{host}/{p.get('linkText', '')}/p"
            produtos.append(Produto(
                titulo=p.get("productName") or sku.get("name") or "", preco=preco,
                preco_original=de if de and de > preco else None, desconto=_desconto(preco, de),
                link=link.replace("http://", "https://"), imagem=imagens[0].get("imageUrl", "") if imagens else "",
                plataforma="VTEX", loja=nome_da_loja(host),
            ))
            break  # um tamanho/cor por produto já basta
    return produtos


def buscar_vtex(host: str, busca: str = "", quantidade: int = 50) -> List[Produto]:
    url = f"https://{host}/api/catalog_system/pub/products/search?_from=0&_to={min(quantidade, 50) - 1}"
    if busca:
        url += "&ft=" + quote(busca)
    # Ordenado pelo maior desconto: as melhores ofertas vêm primeiro (algumas lojas não aceitam a ordenação)
    try:
        dados = _get(url + "&O=OrderByBestDiscountDESC")
    except LojaNaoSuportada:
        dados = None
    dados = dados or _get(url)
    if not isinstance(dados, list):
        raise LojaNaoSuportada("resposta não é da VTEX")
    return produtos_vtex(dados, host)


# ---- Shopify -------------------------------------------------------------------------

def produtos_shopify(dados: dict, host: str) -> List[Produto]:
    produtos = []
    for p in dados.get("products") or []:
        variantes = [v for v in p.get("variants") or [] if v.get("available", True) and v.get("price")]
        if not variantes:
            continue
        # a variante com o maior desconto
        v = max(variantes, key=lambda v: _desconto(float(v["price"]), float(v.get("compare_at_price") or 0) or None))
        preco, de = float(v["price"]), float(v.get("compare_at_price") or 0) or None
        imagens = p.get("images") or []
        produtos.append(Produto(
            titulo=p.get("title") or "", preco=preco, preco_original=de if de and de > preco else None,
            desconto=_desconto(preco, de), link=f"https://{host}/products/{p.get('handle', '')}",
            imagem=imagens[0].get("src", "") if imagens else "", plataforma="Shopify", loja=nome_da_loja(host),
        ))
    return produtos


def buscar_shopify(host: str, busca: str = "", quantidade: int = 250) -> List[Produto]:
    dados = _get(f"https://{host}/products.json?limit={min(quantidade, 250)}")
    if not isinstance(dados, dict) or "products" not in dados:
        raise LojaNaoSuportada("resposta não é da Shopify")
    return produtos_shopify(dados, host)


LEITORES = {"vtex": buscar_vtex, "shopify": buscar_shopify}


def buscar_na_loja(site: str, busca: str = "", plataforma: Optional[str] = None) -> List[Produto]:
    """Lê as ofertas da loja. Sem `plataforma`, tenta VTEX e depois Shopify.
    Com `busca`, só ficam os produtos que têm essas palavras no nome."""
    host = host_da_loja(site)
    erros = []
    for nome in [plataforma] if plataforma else PLATAFORMAS:
        try:
            produtos = LEITORES[nome](host, busca)
            if busca:
                produtos = [p for p in produtos if tem_palavras(p.titulo, busca)]
            log.info("[loja] %s: %d produto(s) lidos (%s)", host, len(produtos), nome.upper())
            return produtos
        except (LojaNaoSuportada, ValueError, requests.RequestException) as e:
            erros.append(f"{nome}: {e}")
    raise LojaNaoSuportada(f"{host} não é VTEX nem Shopify ({'; '.join(erros)})")
