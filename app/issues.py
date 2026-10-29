"""
Configuração por formulário: cada "issue" aberto no GitHub com um dos formulários de
.github/ISSUE_TEMPLATE vira um item monitorado. Fechar o issue = parar de monitorar.

Por segurança (o repositório é público), só valem issues criados pelo dono do repositório
ou por colaboradores.
"""
import logging
import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests
from pydantic import ValidationError

log = logging.getLogger(__name__)

API = "https://api.github.com"
AUTORES_PERMITIDOS = {"OWNER", "COLLABORATOR", "MEMBER"}
SEM_RESPOSTA = {"", "_no response_", "none", "nenhum", "-"}

# Título de cada campo do formulário → nome do campo no monitor
CAMPOS = {
    "voo": {
        "aeroporto de origem": "origem",
        "aeroporto de destino": "destino",
        "data de ida": "ida",
        "ou: ida daqui a quantos dias": "ida_em_dias",
        "quantos dias de viagem": "duracao_dias",
        "adultos": "adultos",
        "preço máximo (r$)": "preco_max",
        "quando avisar": "so_preco_baixo",
    },
    "hospedagem": {
        "onde": "local",
        "data de entrada": "checkin",
        "ou: entrada daqui a quantos dias": "checkin_em_dias",
        "noites": "noites",
        "adultos": "adultos",
        "diária máxima (r$)": "diaria_max",
        "nota mínima": "nota_min",
    },
    "produto": {
        "produto": "termo",
        "preço mínimo (r$)": "preco_min",
        "preço máximo (r$)": "preco_max",
        "desconto mínimo (%)": "desconto_min",
    },
    "anuncio": {
        "nome": "nome",
        "palavras": "palavras",
        "blogs (feeds rss)": "feeds",
        "posts dos últimos quantos dias": "ultimos_dias",
    },
    "loja": {
        "site da loja": "site",
        "só produtos com estas palavras": "busca",
        "desconto mínimo (%)": "desconto_min",
        "preço máximo (r$)": "preco_max",
    },
}
# Campo que identifica o tipo do formulário
MARCADORES = {"aeroporto de origem": "voo", "onde": "hospedagem", "produto": "produto", "blogs (feeds rss)": "anuncio",
              "site da loja": "loja"}


def ler_formulario(corpo: str) -> Dict[str, str]:
    """O GitHub grava o formulário como '### Título do campo' seguido da resposta."""
    campos = {}
    for bloco in re.split(r"^###\s+", corpo or "", flags=re.M)[1:]:
        titulo, _, valor = bloco.partition("\n")
        campos[titulo.strip().lower()] = valor.strip()
    return campos


def _numero(texto: str) -> Optional[float]:
    texto = re.sub(r"[^\d,\.]", "", texto)
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif texto.count(".") == 1 and len(texto.split(".")[1]) == 3:
        texto = texto.replace(".", "")  # "1.500" = mil e quinhentos
    try:
        return float(texto)
    except ValueError:
        raise ValueError(f"'{texto}' não é um número")


def _data(texto: str) -> str:
    for formato in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%Y"):
        try:
            return datetime.strptime(texto.strip(), formato).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f"data '{texto}' inválida (use DD/MM/AAAA)")


def _converter(tipo: str, chave: str, valor: str):
    if chave in ("ida", "checkin"):
        return _data(valor)
    if chave == "so_preco_baixo":
        return "barato" in valor.lower() or "normal" in valor.lower()
    if chave == "nota_min":
        return 0.0 if "qualquer" in valor.lower() else _numero(valor)
    if chave in ("palavras",):
        return [p.strip() for p in re.split(r"[,;\n]", valor) if p.strip()]
    if chave == "feeds":
        return [linha.strip() for linha in valor.splitlines() if linha.strip().startswith("http")]
    if chave in ("ida_em_dias", "duracao_dias", "adultos", "noites", "checkin_em_dias", "desconto_min", "ultimos_dias"):
        return int(_numero(valor))
    if chave in ("preco_max", "diaria_max", "preco_min"):
        return _numero(valor)
    return valor.strip()


def interpretar(corpo: str) -> Tuple[Optional[str], dict]:
    """Devolve (tipo, dados) a partir do texto do issue. tipo=None se não for um formulário do PromoHunter."""
    campos = ler_formulario(corpo)
    tipo = next((t for marcador, t in MARCADORES.items() if marcador in campos), None)
    if not tipo:
        return None, {}
    dados = {}
    for titulo, chave in CAMPOS[tipo].items():
        valor = campos.get(titulo, "")
        if valor.strip().lower() in SEM_RESPOSTA:
            continue
        dados[chave] = _converter(tipo, chave, valor)
    return tipo, dados


# ---- API do GitHub --------------------------------------------------------------

def _cabecalhos() -> dict:
    return {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json"}


def _repo() -> str:
    return os.environ["GITHUB_REPOSITORY"]


def disponivel() -> bool:
    return bool(os.environ.get("GITHUB_TOKEN") and os.environ.get("GITHUB_REPOSITORY"))


def listar_issues_abertos() -> List[dict]:
    r = requests.get(f"{API}/repos/{_repo()}/issues", headers=_cabecalhos(),
                     params={"state": "open", "per_page": 100}, timeout=20)
    r.raise_for_status()
    return [i for i in r.json() if "pull_request" not in i]


def buscar_issue(numero: int) -> dict:
    r = requests.get(f"{API}/repos/{_repo()}/issues/{numero}", headers=_cabecalhos(), timeout=20)
    r.raise_for_status()
    return r.json()


def comentar(numero: int, texto: str):
    try:
        r = requests.post(f"{API}/repos/{_repo()}/issues/{numero}/comments", headers=_cabecalhos(),
                          json={"body": texto}, timeout=20)
        r.raise_for_status()
    except Exception as e:  # comentar é um extra: nunca derruba o monitoramento
        log.warning("Não consegui comentar no issue #%s: %s", numero, e)


def autor_permitido(issue: dict) -> bool:
    return issue.get("author_association") in AUTORES_PERMITIDOS


def html_para_markdown(html: str) -> str:
    """Converte a mensagem do Telegram (HTML simples) para o comentário do GitHub."""
    texto = re.sub(r'<a href="([^"]+)">(.*?)</a>', r"[\2](\1)", html)
    texto = re.sub(r"</?b>", "**", texto)
    texto = re.sub(r"</?s>", "~~", texto)
    texto = re.sub(r"<[^>]+>", "", texto)
    return texto.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')


def erro_legivel(e: Exception) -> str:
    if isinstance(e, ValidationError):
        partes = []
        for erro in e.errors():
            campo = ".".join(str(x) for x in erro["loc"]) or "formulário"
            partes.append(f"- **{campo}**: {erro['msg'].removeprefix('Value error, ')}")
        return "\n".join(partes)
    return f"- {e}"
