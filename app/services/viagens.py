"""Passagens aéreas (Google Voos) e hospedagens (Google Hotéis) via SerpApi."""
import re
from datetime import date
from typing import List, Optional

import requests

from app.config import settings
from app.models import Hospedagem, ResultadoVoos, TrechoVoo, Voo

SERPAPI_URL = "https://serpapi.com/search.json"
SELOS = {"deal": "Promoção", "great deal": "Ótima promoção", "good deal": "Boa promoção"}


def _serpapi(params: dict) -> dict:
    """Faz a chamada e transforma erros da SerpApi em mensagens claras. Gasta 1 busca do plano."""
    params = {"gl": "br", "hl": "pt-br", **params, "api_key": settings.serpapi_key}
    r = requests.get(SERPAPI_URL, params=params, timeout=60)
    dados = r.json() if r.content else {}
    if dados.get("error"):
        if "hasn't returned any results" in dados["error"]:
            return {}
        raise RuntimeError(f"SerpApi: {dados['error']}")
    r.raise_for_status()
    return dados


def _oferta(p: dict) -> str:
    """Junta e traduz os selos de oferta do Google ('Great Deal', '22% less than usual')."""
    partes = []
    for valor in (p.get("deal_description"), p.get("deal")):
        texto = (valor or "").strip()
        if not texto:
            continue
        texto = SELOS.get(texto.lower(), texto)
        texto = re.sub(r"(\d+)\s*% less than usual", r"\1% abaixo do normal", texto, flags=re.I)
        if texto not in partes:
            partes.append(texto)
    return " · ".join(partes)


def _numero(valor) -> Optional[float]:
    try:
        return float(valor) if valor is not None else None
    except (TypeError, ValueError):
        return None


def buscar_voos(origem: str, destino: str, ida: date, volta: Optional[date] = None, adultos: int = 1) -> ResultadoVoos:
    params = {
        "engine": "google_flights",
        "departure_id": origem.upper(),
        "arrival_id": destino.upper(),
        "outbound_date": ida.isoformat(),
        "type": 1 if volta else 2,  # 1 = ida e volta, 2 = só ida
        "adults": adultos,
        "currency": "BRL",
    }
    if volta:
        params["return_date"] = volta.isoformat()
    dados = _serpapi(params)

    voos = []
    for opcao in (dados.get("best_flights") or []) + (dados.get("other_flights") or []):
        preco = _numero(opcao.get("price"))
        trechos = opcao.get("flights") or []
        if not preco or not trechos:
            continue
        companhias = sorted({t.get("airline", "") for t in trechos if t.get("airline")})
        voos.append(Voo(
            preco=preco,
            companhia=" + ".join(companhias),
            escalas=len(trechos) - 1,
            duracao_min=int(opcao.get("total_duration") or 0),
            trechos=[TrechoVoo(
                companhia=t.get("airline", ""),
                saida=(t.get("departure_airport") or {}).get("id", ""),
                chegada=(t.get("arrival_airport") or {}).get("id", ""),
                horario_saida=(t.get("departure_airport") or {}).get("time", ""),
            ) for t in trechos],
        ))
    voos.sort(key=lambda v: (v.preco, v.escalas, v.duracao_min))

    insights = dados.get("price_insights") or {}
    faixa = insights.get("typical_price_range")
    return ResultadoVoos(
        voos=voos,
        nivel_preco=insights.get("price_level") or "",
        faixa_tipica=[float(x) for x in faixa] if isinstance(faixa, list) and len(faixa) == 2 else None,
        link=(dados.get("search_metadata") or {}).get("google_flights_url", ""),
    )


def buscar_hospedagens(local: str, checkin: date, checkout: date, adultos: int = 2) -> List[Hospedagem]:
    dados = _serpapi({
        "engine": "google_hotels",
        "q": local,
        "check_in_date": checkin.isoformat(),
        "check_out_date": checkout.isoformat(),
        "adults": adultos,
        "currency": "BRL",
    })
    link_busca = (dados.get("search_metadata") or {}).get("google_hotels_url", "")

    hospedagens = []
    for p in dados.get("properties") or []:
        diaria = _numero((p.get("rate_per_night") or {}).get("extracted_lowest"))
        if not diaria:
            continue
        imagens = p.get("images") or []
        hospedagens.append(Hospedagem(
            nome=p.get("name", ""),
            diaria=diaria,
            total=_numero((p.get("total_rate") or {}).get("extracted_lowest")),
            nota=_numero(p.get("overall_rating")) or 0,
            avaliacoes=int(p.get("reviews") or 0),
            tipo=p.get("type", ""),
            link=p.get("link") or link_busca,
            imagem=(imagens[0].get("original_image") or imagens[0].get("thumbnail") or "") if imagens else "",
            oferta=_oferta(p),
        ))
    return sorted(hospedagens, key=lambda h: h.diaria)
