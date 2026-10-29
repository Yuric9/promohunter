"""
Teste: quais endpoints oficiais do Mercado Livre o aplicativo consegue usar.
Uso (com ML_CLIENT_ID e ML_CLIENT_SECRET no ambiente): python tools/testar_ml.py
Não mostra a chave de acesso.
"""
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.services.mercadolivre import obter_token  # noqa: E402

API = "https://api.mercadolibre.com"


def mostrar(nome, r):
    print(f"\n=== {nome}: HTTP {r.status_code}")
    print(r.text[:700].replace("\n", " "))


if __name__ == "__main__":
    h = {"Authorization": f"Bearer {obter_token()}"}
    print("chave de acesso: OK")
    r = requests.get(f"{API}/products/search", params={"status": "active", "site_id": "MLB", "q": "tenis masculino"},
                     headers=h, timeout=20)
    mostrar("catálogo: /products/search", r)
    prod = (r.json().get("results") or [{}])[0].get("id") if r.ok else None
    if prod:
        mostrar(f"produto: /products/{prod}", requests.get(f"{API}/products/{prod}", headers=h, timeout=20))
        mostrar(f"anúncios do produto: /products/{prod}/items",
                requests.get(f"{API}/products/{prod}/items", headers=h, timeout=20))
    r = requests.get(f"{API}/highlights/MLB/category/MLB1055", headers=h, timeout=20)
    mostrar("mais vendidos (celulares): /highlights/MLB/category/MLB1055", r)
    destaque = next((c["id"] for c in (r.json().get("content") or []) if c.get("type") == "PRODUCT"), None) if r.ok else None
    if destaque:
        mostrar(f"produto em destaque: /products/{destaque}",
                requests.get(f"{API}/products/{destaque}", headers=h, timeout=20))
        mostrar(f"anúncios do produto em destaque: /products/{destaque}/items",
                requests.get(f"{API}/products/{destaque}/items", headers=h, timeout=20))
    mostrar("busca por categoria: /sites/MLB/search?category=MLB1055",
            requests.get(f"{API}/sites/MLB/search", params={"category": "MLB1055"}, headers=h, timeout=20))
    mostrar("promoções do dia: /sites/MLB/search?promotion_type=deal_of_the_day",
            requests.get(f"{API}/sites/MLB/search", params={"promotion_type": "deal_of_the_day"}, headers=h, timeout=20))
