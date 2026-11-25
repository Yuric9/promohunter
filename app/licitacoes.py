"""
Licitações em aberto de Trindade-GO e cidades próximas (fonte: API pública do PNCP).
- GitHub Actions roda `python -m app.licitacoes`: avisa as novas, alerta prazos e manda o resumo diário.
  Em Trindade entram todas; nas cidades vizinhas, só as de tecnologia.
- O robô na Vercel chama processar() para responder /vigentes, /pregoes e /buscar.
"""
import json
import os
import re
import time
import unicodedata
from datetime import datetime, timedelta, timezone

import requests

from app import bot
from app.config import settings

PNCP = "https://pncp.gov.br/api/consulta/v1/contratacoes/proposta"
TRINDADE_IBGE = "5221403"
VIZINHAS = {  # códigos do IBGE
    "5208707": "Goiânia", "5201405": "Aparecida de Goiânia", "5208806": "Goianira",
    "5200050": "Abadia de Goiás", "5219100": "Santa Bárbara de Goiás", "5204607": "Campestre de Goiás",
    "5209200": "Guapó", "5205208": "Caturaí",
}
# "sistema" sozinho fica de fora: aparece em "Sistema de Registro de Preços" e "Sistema Único de Saúde"
TECNOLOGIA = re.compile(
    r"\b(softwares?|informatica|computador(es)?|notebooks?|impressoras?|tecnologia da informacao|"
    r"sistemas? (informatizados?|de informacao|de gestao|web)|desenvolvimento de (sistemas?|sites?)|"
    r"licencas? de uso|websites?|criacao de sites?|sitio eletronico|aplicativos?|internet|"
    r"rede de dados|data ?center|equipamentos de ti)\b")
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


def buscar(modalidades=TODAS, timeout=30, limite_segundos=None, cidade=TRINDADE_IBGE, tentativas=1):
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
                params = {"dataFinal": (agora + timedelta(days=365)).strftime("%Y%m%d"),
                          "codigoModalidadeContratacao": modalidade, "codigoMunicipioIbge": cidade,
                          "pagina": pagina, "tamanhoPagina": 50}
                for tentativa in range(1, tentativas + 1):
                    try:
                        r = requests.get(PNCP, timeout=timeout, params=params)
                        if r.status_code != 204:
                            r.raise_for_status()
                        corpo = None if r.status_code == 204 else r.json()
                        break
                    except (requests.RequestException, ValueError):
                        if tentativa == tentativas:
                            raise
                        time.sleep(5 * tentativa)
                if corpo is None:  # 204 = nenhum resultado
                    break
                itens += corpo.get("data") or []
                total = corpo.get("totalPaginas") or 1
                pagina += 1
        except (requests.RequestException, ValueError, TimeoutError) as e:
            avisos.append(f"modalidade {modalidade}: {e}")
    vigentes = [i for i in itens
                if i.get("situacaoCompraId") in (None, 1) and (_prazo(i) is None or _prazo(i) > agora)]
    vigentes.sort(key=lambda i: i.get("dataEncerramentoProposta") or "9999")
    return vigentes, avisos


def eh_tecnologia(i: dict) -> bool:
    return bool(TECNOLOGIA.search(_sem_acento(i.get("objetoCompra") or "")))


def buscar_regiao():
    """Trindade completa + só tecnologia nas vizinhas. Devolve (itens, avisos, total de consultas)."""
    itens, avisos = buscar(tentativas=3)
    avisos = [f"Trindade, {a}" for a in avisos]
    inicio = time.monotonic()
    for codigo, nome in VIZINHAS.items():
        # se o PNCP estiver muito lento, não deixa as vizinhas atrasarem o envio de Trindade
        if time.monotonic() - inicio > 15 * 60:
            avisos += [f"{nome}, modalidade {m}: tempo esgotado" for m in TODAS]
            continue
        achados, falhas = buscar(cidade=codigo, tentativas=2)
        itens += filter(eh_tecnologia, achados)
        avisos += [f"{nome}, {a}" for a in falhas]
    itens.sort(key=lambda i: i.get("dataEncerramentoProposta") or "9999")
    return itens, avisos, len(TODAS) * (1 + len(VIZINHAS))


def resumo(i: dict) -> str:
    cnpj = (i.get("orgaoEntidade") or {}).get("cnpj")
    prazo = _prazo(i)
    cidade = (i.get("unidadeOrgao") or {}).get("municipioNome") or "Cidade não informada"
    destaque = "⭐ TECNOLOGIA | " if eh_tecnologia(i) else ""
    return "\n".join([
        f"{destaque}{cidade}",
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


def _alertas_de_prazo(item: dict, agora: datetime) -> list:
    """Marcas de prazo já alcançadas: 3 dias e/ou 1 dia para encerrar."""
    prazo = _prazo(item)
    if not prazo:
        return []
    return [dias for dias in (3, 1) if prazo - agora <= timedelta(days=dias)]


def monitorar(pausa: float = 1.5, resumo_diario: bool = False) -> int:
    """Envia o resumo diário ou as novidades, e os alertas de prazo. Devolve quantas mensagens enviou."""
    destino = settings.dono_chat_id
    if not destino:
        raise SystemExit("Cadastre o secret TELEGRAM_DONO (seu número no Telegram).")
    itens, avisos, consultas = buscar_regiao()
    for aviso in avisos:
        print("Falha no PNCP:", aviso)
    if len(avisos) == consultas:
        raise SystemExit("PNCP indisponível.")
    arquivo = settings.data_dir / "licitacoes_vistas.json"
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    primeira = not arquivo.exists()
    # guarda os ids já enviados e as marcas de prazo já alertadas ("id|3", "id|1")
    vistas = set() if primeira else set(json.loads(arquivo.read_text()))
    agora = datetime.now(BRASILIA)
    enviadas = 0

    def mandar(texto: str, marcas: list):
        nonlocal enviadas
        enviar(destino, texto)
        enviadas += 1
        vistas.update(marcas)
        arquivo.write_text(json.dumps(sorted(vistas)))
        time.sleep(pausa)

    if resumo_diario or primeira:
        alerta = [f"Atenção: lista incompleta, {len(avisos)} consulta(s) ao PNCP falharam."] if avisos else []
        titulo = (f"Resumo de {agora:%d/%m}: {len(itens)} oportunidade(s) aberta(s)\n"
                  "Trindade: todas. Cidades vizinhas: só tecnologia.")
        mensagens = dividir([titulo, *alerta, *map(resumo, itens)])
        for numero, mensagem in enumerate(mensagens, 1):
            # só marca como vistas depois que a última parte for enviada
            mandar(mensagem, [i["numeroControlePNCP"] for i in itens] if numero == len(mensagens) else [])
    else:
        for item in itens:
            chave = item["numeroControlePNCP"]
            if chave not in vistas:
                marcas = [f"{chave}|{d}" for d in _alertas_de_prazo(item, agora)]
                mandar("Nova oportunidade\n" + resumo(item), [chave, *marcas])

    for item in itens:
        chave = item["numeroControlePNCP"]
        dias = _alertas_de_prazo(item, agora)
        pendentes = [d for d in dias if f"{chave}|{d}" not in vistas]
        if pendentes:
            falta = "menos de 24 horas" if 1 in dias else "3 dias ou menos"
            mandar(f"⏰ Prazo encerrando: {falta}\n" + resumo(item), [f"{chave}|{d}" for d in dias])
    return enviadas


if __name__ == "__main__":
    print("Mensagens enviadas:", monitorar(resumo_diario=os.getenv("RESUMO") == "true"))
