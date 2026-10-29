"""
Teste rápido: descobre como cada site pode ser lido de graça.
- VTEX:    /api/catalog_system/pub/products/search  (traz preço "de" e "por")
- Shopify: /products.json                           (traz price e compare_at_price)
- Feed:    /feed                                    (blogs de promoção de viagem)
Uso: python tools/testar_lojas.py           (descobre a plataforma de cada site)
     python tools/testar_lojas.py ofertas   (lê as ofertas de 20%+ das lojas do monitoramento.yml)
"""
import json
import sys
import xml.etree.ElementTree as ET

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/130.0 Safari/537.36", "Accept": "application/json,text/html;q=0.9,*/*;q=0.8"}

LOJAS = {
    "Tênis e calçados": [
        "www.netshoes.com.br", "www.centauro.com.br", "www.artwalk.com.br", "www.authenticfeet.com.br",
        "www.nike.com.br", "www.adidas.com.br", "www.mizuno.com.br", "www.asics.com.br", "www.olympikus.com.br",
        "www.fila.com.br", "br.puma.com", "www.newbalance.com.br", "www.underarmour.com.br", "www.vans.com.br",
        "www.converse.com.br", "www.tf.com.br", "www.dafiti.com.br", "www.zattini.com.br", "www.kanui.com.br",
        "www.ofertasonline.com.br", "www.magicfeet.com.br", "www.lojavirus.com.br",
    ],
    "Roupas masculinas": [
        "www.usereserva.com", "www.hering.com.br", "www.insiderstore.com.br", "www.aramis.com.br",
        "www.richards.com.br", "www.colcci.com.br", "www.lacoste.com.br", "br.tommy.com", "www.calvinklein.com.br",
        "www.dzarm.com.br", "www.lojasrenner.com.br", "www.riachuelo.com.br", "www.cea.com.br", "www.osklen.com.br",
        "www.foxtonbrasil.com.br", "www.basicamente.com.br", "www.highcompany.com.br", "www.levi.com.br",
        "www.lojalevis.com.br", "www.taco.com.br", "www.mash.com.br", "www.oficinareserva.com.br",
    ],
    "Tecnologia": [
        "www.kabum.com.br", "www.pichau.com.br", "www.terabyteshop.com.br", "www.fastshop.com.br",
        "www.samsung.com", "www.motorola.com.br", "www.lenovo.com", "www.dell.com", "loja.positivo.com.br",
        "www.multilaser.com.br", "www.jbl.com.br", "www.mi.com", "www.carrefour.com.br", "www.casasbahia.com.br",
        "www.magazineluiza.com.br", "www.americanas.com.br", "www.girafa.com.br", "www.mercadolivre.com.br",
        "www.amazon.com.br", "www.gocase.com.br", "www.havan.com.br", "www.extra.com.br", "www.pontofrio.com.br",
        "www.lg.com", "www.philco.com.br", "www.mondial.com.br", "www.electrolux.com.br", "www.brastemp.com.br",
        "www.consul.com.br", "www.compracerta.com.br", "www.efacil.com.br", "www.shopfacil.com.br",
    ],
}

FEEDS = [
    "https://www.melhoresdestinos.com.br/feed", "https://passagensimperdiveis.com.br/feed",
    "https://www.passageirodeprimeira.com/feed", "https://pontospravoar.com/feed",
    "https://www.viajenaviagem.com/feed", "https://www.promocoesaereas.com.br/feed",
    "https://www.mochileiros.com/feed", "https://www.vaidepromo.com.br/blog/feed",
    "https://blog.maxmilhas.com.br/feed", "https://www.123milhas.com/blog/feed",
    "https://www.hoteis.com/blog/feed", "https://www.dicasdeviagem.com/feed",
    "https://www.viagensecaminhos.com/feed", "https://www.queroviajarmais.com/feed",
    "https://www.melhoresdestinos.com.br/hoteis/feed", "https://blog.decolar.com/feed",
    "https://www.promobit.com.br/blog/feed", "https://www.pelando.com.br/api/feeds/deals",
    "https://www.hardmob.com.br/external.php?type=RSS2&forumids=407",
    "https://www.gatry.com/feed", "https://www.ofertaesperta.com/feed",
]


def vtex(host):
    r = requests.get(f"https://{host}/api/catalog_system/pub/products/search?_from=0&_to=4",
                     headers=UA, timeout=20)
    if r.status_code not in (200, 206):
        return None, f"vtex {r.status_code}"
    dados = r.json()
    if not isinstance(dados, list) or not dados:
        return None, "vtex vazio"
    oferta = dados[0]["items"][0]["sellers"][0]["commertialOffer"]
    return "VTEX", f"{dados[0]['productName'][:40]} | de {oferta.get('ListPrice')} por {oferta.get('Price')}"


def shopify(host):
    r = requests.get(f"https://{host}/products.json?limit=5", headers=UA, timeout=20)
    if r.status_code != 200:
        return None, f"shopify {r.status_code}"
    produtos = r.json().get("products") or []
    if not produtos:
        return None, "shopify vazio"
    v = produtos[0]["variants"][0]
    return "Shopify", f"{produtos[0]['title'][:40]} | de {v.get('compare_at_price')} por {v.get('price')}"


def pagina(host):
    r = requests.get(f"https://{host}/", headers=UA, timeout=20)
    sinais = [n for n in ("vtex", "shopify", "magento", "vnda", "nuvemshop", "tray", "wake", "salesforce",
                          "demandware", "occ", "next") if n in r.text.lower()[:300000]]
    return f"página {r.status_code} {len(r.text)//1024}KB sinais={','.join(sinais) or '-'}"


def testar_loja(host):
    notas = []
    for leitor in (vtex, shopify):
        try:
            tipo, info = leitor(host)
            if tipo:
                return tipo, info
            notas.append(info)
        except Exception as e:
            notas.append(f"{leitor.__name__} erro {type(e).__name__}")
    try:
        notas.append(pagina(host))
    except Exception as e:
        notas.append(f"página erro {type(e).__name__}")
    return "—", " ; ".join(notas)


def testar_feed(url):
    try:
        r = requests.get(url, headers=UA, timeout=20)
        if r.status_code != 200:
            return f"❌ {r.status_code}"
        raiz = ET.fromstring(r.content)
        itens = list(raiz.iter("item")) or list(raiz.iter("{http://www.w3.org/2005/Atom}entry"))
        titulo = itens[0].findtext("title") if itens else ""
        return f"✅ {len(itens)} posts | {titulo[:60]}"
    except Exception as e:
        return f"❌ {type(e).__name__}"


def testar_ofertas():
    """Mostra o que seria postado agora (mesma lógica do monitor, nada é enviado)."""
    import logging
    import os
    import tempfile
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app import monitor
    from app.config import settings
    settings.data_dir = __import__("pathlib").Path(tempfile.mkdtemp())  # ignora o histórico de enviados
    logging.basicConfig(level=logging.WARNING)
    for item in monitor.carregar().lojas:
        try:
            posts = monitor.posts_loja(item)
        except Exception as e:
            print(f"❌ {item.titulo}: {e}")
            continue
        print(f"\n🏬 {item.titulo}: {len(posts)} oferta(s) para postar")
        for post in posts:
            print("   " + " | ".join(linha for linha in post.texto.splitlines()[:4]))


if __name__ == "__main__":
    if sys.argv[1:] == ["ofertas"]:
        testar_ofertas()
        sys.exit(0)
    resultado = {}
    for categoria, hosts in LOJAS.items():
        print(f"\n=== {categoria} ===")
        for host in hosts:
            tipo, info = testar_loja(host)
            resultado[host] = tipo
            print(f"{tipo:8} {host:30} {info}")
    print("\n=== Feeds de viagem / promoções ===")
    for url in FEEDS:
        print(f"{url:65} {testar_feed(url)}")
    print("\nRESUMO", json.dumps(resultado))
    sys.exit(0)
