"""Promoções publicadas em blogs de ofertas, lidas pelo feed RSS/Atom (não gasta busca da SerpApi)."""
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from typing import List, Optional

import requests

from app.models import Anuncio

log = logging.getLogger(__name__)
ATOM = "{http://www.w3.org/2005/Atom}"
BRASILIA = timezone(timedelta(hours=-3))


def _texto(el, tag: str) -> str:
    achado = el.find(tag)
    return (achado.text or "").strip() if achado is not None and achado.text else ""


def _limpar(html: str, limite: int = 220) -> str:
    texto = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html))).strip()
    texto = re.sub(r"\s+([.,;:!?])", r"\1", texto)
    return texto if len(texto) <= limite else texto[:limite - 3].rsplit(" ", 1)[0] + "..."


def _data(valor: str) -> Optional[datetime]:
    if not valor:
        return None
    try:
        d = parsedate_to_datetime(valor)  # formato RSS
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(valor.replace("Z", "+00:00"))  # formato Atom
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def ler_feed(url: str) -> List[Anuncio]:
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (PromoHunter)"}, timeout=20)
    r.raise_for_status()
    raiz = ET.fromstring(r.content)
    fonte = _texto(raiz, "channel/title") or _texto(raiz, f"{ATOM}title")
    itens = []
    for item in raiz.iter("item"):  # RSS 2.0
        itens.append((_texto(item, "title"), _texto(item, "link"), _texto(item, "description"), _texto(item, "pubDate")))
    for entry in raiz.iter(f"{ATOM}entry"):  # Atom
        link = entry.find(f"{ATOM}link")
        itens.append((_texto(entry, f"{ATOM}title"), link.get("href", "") if link is not None else "",
                      _texto(entry, f"{ATOM}summary"), _texto(entry, f"{ATOM}updated")))
    anuncios = []
    for titulo, link, resumo, data in itens:
        if not titulo or not link:
            continue
        quando = _data(data)
        anuncios.append(Anuncio(
            titulo=unescape(titulo), link=link, resumo=_limpar(resumo), fonte=fonte, publicado=quando,
            data=quando.astimezone(BRASILIA).strftime("%d/%m %H:%M") if quando else "",
        ))
    return anuncios


def buscar_nos_feeds(feeds: List[str], palavras: Optional[List[str]] = None, ultimos_dias: int = 2) -> List[Anuncio]:
    """Junta os posts recentes dos feeds; com `palavras`, só os que mencionam alguma delas."""
    limite = datetime.now(timezone.utc) - timedelta(days=ultimos_dias)
    termos = [p.lower() for p in palavras or []]
    resultado = []
    for url in feeds:
        try:
            posts = ler_feed(url)
        except Exception as e:
            log.warning("[feed] %s: não consegui ler (%s)", url, e)
            continue
        recentes = [a for a in posts if (a.publicado or limite) >= limite]
        if termos:
            recentes = [a for a in recentes if any(t in f"{a.titulo} {a.resumo}".lower() for t in termos)]
        log.info("[feed] %s: %d post(s), %d recente(s) e dentro das palavras", url, len(posts), len(recentes))
        resultado.extend(recentes)
    return resultado
