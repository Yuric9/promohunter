from typing import Optional

import requests

from app.config import settings
from app.models import Comparativo


def _brl(valor: float) -> str:
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def formatar_mensagem(comp: Comparativo) -> str:
    m = comp.melhor_oferta
    titulo = m.titulo if len(m.titulo) <= 80 else m.titulo[:77] + "..."
    if m.preco_original:
        preco = f"💰 De ~{_brl(m.preco_original)}~ por *{_brl(m.preco)}*\n💵 Economia de {_brl(comp.economia)}"
    else:
        preco = f"💰 *{_brl(m.preco)}*"
    desconto = f" - {m.desconto}% OFF" if m.desconto else ""
    plataformas = " + ".join(sorted({p.plataforma for p in comp.todas_ofertas}))
    return (
        f"🔥 *MELHOR OFERTA* 🔥\n\n"
        f"🔍 *{comp.termo.upper()}*\n\n"
        f"🏆 *{m.plataforma}*{desconto}\n"
        f"📦 {titulo}\n"
        f"{preco}\n\n"
        f"🔗 {m.link}\n\n"
        f"📊 {len(comp.todas_ofertas)} ofertas comparadas ({plataformas})"
    )


def enviar_whatsapp(mensagem: str, numero: Optional[str] = None, grupo_id: Optional[str] = None) -> dict:
    destino = grupo_id or numero or settings.whatsapp_default_group_id or settings.whatsapp_default_number
    if not destino:
        return {"ok": False, "erro": "nenhum número ou grupo configurado"}
    url = f"{settings.evolution_api_url}/message/sendText/{settings.evolution_instance}"
    headers = {"apikey": settings.evolution_api_key, "Content-Type": "application/json"}
    try:
        r = requests.post(url, json={"number": destino, "text": mensagem}, headers=headers, timeout=10)
        r.raise_for_status()
        return {"ok": True, "resposta": r.json()}
    except Exception as e:
        return {"ok": False, "erro": str(e)}
