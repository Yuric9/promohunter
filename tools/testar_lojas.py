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

# Lote 2 de candidatas (o lote 1 já foi testado: resultado no monitoramento.yml)
LOJAS = {
    "Tênis e calçados": [
        "www.reebok.com.br", "www.skechers.com.br", "www.topper.com.br", "www.penalty.com.br",
        "www.diadora.com.br", "www.rainha.com.br", "www.kappa.com.br", "www.umbro.com.br",
        "www.timberland.com.br", "www.ferracini.com.br", "www.democrata.com.br", "www.pegada.com.br",
        "www.samello.com.br", "www.mrcat.com.br", "www.usaflex.com.br", "www.kildare.com.br",
        "www.maze.com.br", "www.gallerist.com.br", "www.sunsetsurf.com.br", "www.hoka.com.br",
        "www.saucony.com.br", "www.oakley.com.br", "www.mormaii.com.br",
        "www.lojamaze.com.br", "www.droper.app", "www.ascsneakers.com.br", "www.lojaonrunning.com.br",
    ],
    "Roupas masculinas": [
        "www.redley.com.br", "www.dudalina.com.br", "www.individual.com.br", "www.vrcollezioni.com.br",
        "www.siberian.com.br", "www.brooksfield.com.br", "www.forum.com.br", "www.ellus.com.br",
        "www.tng.com.br", "www.hurley.com.br", "www.quiksilver.com.br", "www.billabong.com.br",
        "www.lupo.com.br", "www.polowear.com.br", "www.malwee.com.br", "www.piticas.com.br",
        "www.cavalera.com.br", "www.aleatory.com.br", "www.osmoze.com.br", "www.sergiok.com.br",
        "www.zerezes.com.br", "www.approve.com.br", "www.chicorei.com", "www.ogochi.com.br",
        "www.youcom.com.br", "www.oqvestir.com.br", "www.studioz.com.br", "www.colombo.com.br",
        "www.hangloose.com.br", "www.fatalsurf.com.br",
    ],
    "Tecnologia": [
        "www.shoptime.com.br", "www.submarino.com.br", "www.iplace.com.br", "www.ibyte.com.br",
        "www.gazin.com.br", "www.lojaskoerich.com.br", "www.novomundo.com.br", "www.casaevideo.com.br",
        "www.webcontinental.com.br", "www.lebiscuit.com.br", "loja.intelbras.com.br", "www.aiwa.com.br",
        "www.redragon.com.br", "www.logitechstore.com.br", "www.vaio.com.br", "www.i2go.com.br",
        "www.elgin.com.br", "www.tcl.com", "www.positivotecnologia.com.br", "www.mondaine.com.br",
        "www.technos.com.br", "www.relogiosmagnum.com.br", "www.haylou.com.br", "www.amazfit.com.br",
        "www.lojaxiaomi.com.br", "www.xiaomistore.com.br", "www.gshield.com.br", "www.baseus.com.br",
        "www.anker.com.br", "www.edifier.com.br", "www.kalunga.com.br", "www.zoom.com.br",
    ],
    "Viagem (malas e acessórios)": [
        "www.samsonite.com.br", "www.sestini.com.br", "www.americantourister.com.br", "www.travelmate.com.br",
        "www.primicia.com.br", "www.jacki-design.com.br", "www.lojapolo.com.br", "www.yins.com.br",
    ],
}

FEEDS_LOTE1 = [
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

FEEDS = []  # feeds já testados no lote 1


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
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(8) as pool:  # várias lojas ao mesmo tempo, para o teste não demorar
            for host, (tipo, info) in zip(hosts, pool.map(testar_loja, hosts)):
                resultado[host] = tipo
                print(f"{tipo:8} {host:30} {info}")
    print("\n=== Feeds de viagem / promoções ===")
    for url in FEEDS:
        print(f"{url:65} {testar_feed(url)}")
    print("\nRESUMO", json.dumps(resultado))
    sys.exit(0)
