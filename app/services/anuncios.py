"""Promoções anunciadas na internet: busca no Google limitada aos últimos dias (via SerpApi)."""
from typing import List, Optional
from urllib.parse import urlparse

from app.models import Anuncio
from app.services.viagens import _serpapi

PERIODOS = {1: "qdr:d", 7: "qdr:w", 30: "qdr:m"}
# Vídeos e redes sociais raramente são o anúncio da promoção em si
SITES_IGNORADOS = ("youtube.com", "youtu.be", "tiktok.com", "instagram.com", "facebook.com", "x.com", "twitter.com")
SEM_CONTEUDO = ("não há nenhuma informação disponível", "no information is available")


def _dominio(link: str) -> str:
    return urlparse(link).netloc.lower().removeprefix("www.")


def _util(r: dict) -> bool:
    titulo, link = r.get("title", ""), r.get("link", "")
    if not link or not titulo or titulo.startswith("http"):
        return False
    if any(_dominio(link) == s or _dominio(link).endswith("." + s) for s in SITES_IGNORADOS):
        return False
    return not any(t in (r.get("snippet") or "").lower() for t in SEM_CONTEUDO)


def buscar_anuncios(busca: str, ultimos_dias: int = 7, sites: Optional[List[str]] = None,
                    limite: int = 10) -> List[Anuncio]:
    """Só traz páginas publicadas/atualizadas no período, para evitar promoções vencidas.
    Com `sites`, procura apenas nesses sites (ex.: melhoresdestinos.com.br)."""
    dias = min(PERIODOS, key=lambda d: abs(d - ultimos_dias))
    consulta = busca
    if sites:
        consulta += " (" + " OR ".join(f"site:{s}" for s in sites) + ")"
    dados = _serpapi({"engine": "google", "q": consulta, "tbs": PERIODOS[dias], "num": limite})
    return [
        Anuncio(
            titulo=r["title"],
            link=r["link"],
            resumo=r.get("snippet", ""),
            fonte=r.get("source") or _dominio(r["link"]),
            data=r.get("date", ""),
        )
        for r in dados.get("organic_results") or [] if _util(r)
    ]
