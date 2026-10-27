"""Promoções anunciadas na internet: busca no Google limitada aos últimos dias (via SerpApi)."""
from typing import List

from app.models import Anuncio
from app.services.viagens import _serpapi

PERIODOS = {1: "qdr:d", 7: "qdr:w", 30: "qdr:m"}


def buscar_anuncios(busca: str, ultimos_dias: int = 7, limite: int = 10) -> List[Anuncio]:
    """Só traz páginas publicadas/atualizadas no período, para evitar promoções vencidas."""
    dias = min(PERIODOS, key=lambda d: abs(d - ultimos_dias))
    dados = _serpapi({"engine": "google", "q": busca, "tbs": PERIODOS[dias], "num": limite})
    return [
        Anuncio(
            titulo=r.get("title", ""),
            link=r["link"],
            resumo=r.get("snippet", ""),
            fonte=r.get("source") or r.get("displayed_link", ""),
            data=r.get("date", ""),
        )
        for r in dados.get("organic_results") or [] if r.get("link")
    ]
