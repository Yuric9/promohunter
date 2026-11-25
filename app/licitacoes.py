"""
Licitações em aberto de Trindade-GO (fonte: API pública do PNCP).
- GitHub Actions roda `python -m app.licitacoes` e avisa o dono sobre as novas.
- O robô na Vercel chama processar() para responder /vigentes, /pregoes e /buscar.
"""
import json
import os
import time
import unicodedata
from datetime import datetime, timedelta, timezone

import requests

from app import bot
from app.config import settings

PNCP = "https://pncp.gov.br/api/consulta/v1/contratacoes/proposta"
TRINDADE_IBGE = "5221403"
BRASILIA = timezone(timedelta(hours=-3))
PREGOES = (6, 7)
TODAS = (4, 5, 6, 7, 8, 12)  # concorrência, pregão, dispensa e credenciamento
AJUDA = ("Licitações de Trindade-GO\n\n"
         "/vigentes - todas com propostas em aberto\n"
         "/pregoes - só pregões\n"
         "/buscar palavra - procura no objeto")


def _prazo(item: dict):
    texto = item.get("dataEncerramentoProposta")
    if not texto:
        return None
    data = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    return data if data.tzinfo else data.replace(tzinfo=BRASILIA)


def buscar(modalidades=TODAS, timeout=30, limite_segundos=None):
    """Devolve (licitações vigentes, avisos de falha)."""
    inicio = time.monotonic()
    agora = datetime.now(BRASILIA)
    itens, avisos = [], []
    for modalidade in modalidades:
        try:
            pagina = total = 1
            while pagina <= total:
                if limite_segundos and time.monotonic() - inicio > limite_segundos:
                    raise TimeoutError("tempo esgotado")
                r = requests.get(PNCP, timeout=timeout, params={
                    "dataFinal": (agora + timedelta(days=365)).strftime("%Y%m%d"),
                    "codigoModalidadeContratacao": modalidade,
                    "codigoMunicipioIbge": TRINDADE_IBGE,
                    "pagina": pagina, "tamanhoPagina": 50})
                if r.status_code == 204:  # nenhum resultado
                    break
                r.raise_for_status()
                corpo = r.json()
                itens += corpo.get("data") or []
                total = corpo.get("totalPaginas") or 1
                pagina += 1
        except (requests.RequestException, ValueError, TimeoutError) as e:
            avisos.append(f"modalidade {modalidade}: {e}")
    vigentes = [i for i in itens
                if i.get("situacaoCompraId") in (None, 1) and (_prazo(i) is None or _prazo(i) > agora)]
    vigentes.sort(key=lambda i: i.get("dataEncerramentoProposta") or "9999")
    return vigentes, avisos


def resumo(i: dict) -> str:
    cnpj = (i.get("orgaoEntidade") or {}).get("cnpj")
    prazo = _prazo(i)
    return "\n".join([
        f"{i.get('modalidadeNome')} {i.get('numeroCompra')}/{i.get('anoCompra')}",
        str(i.get("objetoCompra") or "")[:300],
        f"Propostas até {prazo:%d/%m/%Y %H:%M}" if prazo else "Prazo não informado",
        f"https://pncp.gov.br/app/editais/{cnpj}/{i.get('anoCompra')}/{i.get('sequencialCompra')}",
    ])


def dividir(blocos: list, limite: int = 3800) -> list:
    """Junta os blocos em mensagens menores que o limite do Telegram."""
    mensagens, atual = [], ""
    for bloco in blocos:
        if atual and len(atual) + len(bloco) + 2 > limite:
            mensagens.append(atual)
            atual = ""
        atual += ("\n\n" if atual else "") + bloco
    return mensagens + ([atual] if atual else [])


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if not unicodedata.combining(c)).lower()


def enviar(chat_id, texto: str):
    resposta = bot.telegram("sendMessage", chat_id=chat_id, text=texto, disable_web_page_preview=True)
    if not resposta.get("ok"):
        raise RuntimeError(f"Telegram recusou: {resposta.get('description')}")


def responder_comando(texto: str) -> list:
    partes = texto.split(maxsplit=1)
    comando = partes[0].lower().split("@")[0]
    palavra = partes[1].strip() if len(partes) > 1 else ""
    if comando not in ("/vigentes", "/pregoes", "/buscar"):
        return [AJUDA]
    if comando == "/buscar" and not palavra:
        return ["Escreva a palavra. Exemplo: /buscar informatica"]
    modalidades = PREGOES if comando == "/pregoes" else TODAS
    # limites curtos porque a Vercel encerra a execução em 60 segundos
    itens, avisos = buscar(modalidades, timeout=8, limite_segundos=35)
    if len(avisos) == len(modalidades):
        return ["Não consegui consultar o PNCP agora. Tente mais tarde."]
    if comando == "/buscar":
        itens = [i for i in itens if _sem_acento(palavra) in _sem_acento(i.get("objetoCompra") or "")]
    alerta = ["Atenção: lista incompleta, o PNCP falhou em parte."] if avisos else []
    mensagens = dividir([f"{len(itens)} licitação(ões) encontrada(s)", *alerta, *map(resumo, itens)])
    if len(mensagens) > 8:
        mensagens = mensagens[:8] + ["A lista é grande. Use /buscar palavra para filtrar."]
    return mensagens


def processar(update: dict):
    """Trata uma mensagem recebida do Telegram (só conversa privada do dono)."""
    msg = update.get("message") or {}
    texto = (msg.get("text") or "").strip()
    chat = msg.get("chat") or {}
    if not texto or chat.get("type") != "private":
        return
    if not bot.autorizado(msg["from"]["id"]):
        enviar(chat["id"], "Este robô é particular.")
        return
    for mensagem in responder_comando(texto):
        enviar(chat["id"], mensagem)


def avisar_novas(pausa: float = 1.5, todas: bool = False) -> int:
    """Avisa o dono sobre as novas; com todas=True, envia a lista completa das vigentes."""
    destino = settings.dono_chat_id
    if not destino:
        raise SystemExit("Cadastre o secret TELEGRAM_DONO (seu número no Telegram).")
    itens, avisos = buscar()
    for aviso in avisos:
        print("Falha no PNCP:", aviso)
    if len(avisos) == len(TODAS):
        raise SystemExit("PNCP indisponível.")
    arquivo = settings.data_dir / "licitacoes_vistas.json"
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    primeira = not arquivo.exists()
    vistas = set() if primeira else set(json.loads(arquivo.read_text()))
    novas = [i for i in itens if i["numeroControlePNCP"] not in vistas]
    if todas:
        alerta = ["Atenção: lista incompleta, o PNCP falhou em parte."] if avisos else []
        blocos = [f"{len(itens)} licitação(ões) vigente(s) em Trindade", *alerta, *map(resumo, itens)]
        for mensagem in dividir(blocos):
            enviar(destino, mensagem)
            time.sleep(pausa)
        vistas |= {i["numeroControlePNCP"] for i in itens}
        arquivo.write_text(json.dumps(sorted(vistas)))
        return len(itens)
    if primeira:
        enviar(destino, f"Monitor ativado: {len(itens)} licitações vigentes em Trindade. Envie /vigentes.")
        arquivo.write_text(json.dumps([i["numeroControlePNCP"] for i in itens]))
        return 0
    for item in novas:
        enviar(destino, "Nova licitação em Trindade\n" + resumo(item))
        vistas.add(item["numeroControlePNCP"])
        arquivo.write_text(json.dumps(sorted(vistas)))
        time.sleep(pausa)
    return len(novas)


if __name__ == "__main__":
    print("Enviadas:", avisar_novas(todas=os.getenv("ENVIAR_TODAS") == "true"))
