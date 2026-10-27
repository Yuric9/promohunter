"""
Entende um pedido escrito livremente ("passagem goiânia recife 20/12 a 27/12",
"iphone 17 128gb até 6000", "pousada em pirenópolis 15/11 2 noites") e decide
o que pesquisar: voo, hospedagem ou produto.
"""
import re
import unicodedata
from datetime import date, timedelta
from typing import List, Optional, Tuple

from pydantic import BaseModel


def sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")


# Cidade → aeroporto(s). Vários aeroportos separados por vírgula (o Google Voos aceita).
AEROPORTOS = {
    "goiania": "GYN", "brasilia": "BSB", "sao paulo": "GRU,CGH,VCP", "sp": "GRU,CGH,VCP", "guarulhos": "GRU",
    "congonhas": "CGH", "campinas": "VCP", "rio de janeiro": "GIG,SDU", "rio": "GIG,SDU", "belo horizonte": "CNF,PLU",
    "bh": "CNF,PLU", "confins": "CNF", "recife": "REC", "salvador": "SSA", "fortaleza": "FOR", "natal": "NAT",
    "maceio": "MCZ", "joao pessoa": "JPA", "aracaju": "AJU", "sao luis": "SLZ", "teresina": "THE", "belem": "BEL",
    "manaus": "MAO", "porto alegre": "POA", "florianopolis": "FLN", "floripa": "FLN", "curitiba": "CWB",
    "vitoria": "VIX", "campo grande": "CGR", "cuiaba": "CGB", "porto seguro": "BPS", "foz do iguacu": "IGU",
    "navegantes": "NVT", "palmas": "PMW", "porto velho": "PVH", "macapa": "MCP", "boa vista": "BVB",
    "rio branco": "RBR", "uberlandia": "UDI", "ribeirao preto": "RAO", "caldas novas": "CLV", "londrina": "LDB",
    "maringa": "MGF", "ilheus": "IOS", "fernando de noronha": "FEN", "noronha": "FEN", "jericoacoara": "JJD",
    "lisboa": "LIS", "porto": "OPO", "madri": "MAD", "madrid": "MAD", "barcelona": "BCN", "paris": "CDG,ORY",
    "londres": "LHR,LGW", "roma": "FCO", "milao": "MXP", "amsterda": "AMS", "frankfurt": "FRA", "miami": "MIA",
    "orlando": "MCO", "nova york": "JFK,EWR", "new york": "JFK,EWR", "buenos aires": "EZE,AEP", "santiago": "SCL",
    "montevideu": "MVD", "lima": "LIM", "bogota": "BOG", "cancun": "CUN", "punta cana": "PUJ",
    "cidade do mexico": "MEX", "dubai": "DXB", "toquio": "HND,NRT",
}
NOMES = {  # como mostrar a cidade (com acento)
    "goiania": "Goiânia", "brasilia": "Brasília", "sao paulo": "São Paulo", "sp": "São Paulo",
    "rio de janeiro": "Rio de Janeiro", "rio": "Rio de Janeiro", "bh": "Belo Horizonte", "maceio": "Maceió",
    "joao pessoa": "João Pessoa", "sao luis": "São Luís", "belem": "Belém", "florianopolis": "Florianópolis",
    "floripa": "Florianópolis", "vitoria": "Vitória", "cuiaba": "Cuiabá", "foz do iguacu": "Foz do Iguaçu",
    "macapa": "Macapá", "uberlandia": "Uberlândia", "ribeirao preto": "Ribeirão Preto", "maringa": "Maringá",
    "ilheus": "Ilhéus", "fernando de noronha": "Fernando de Noronha", "noronha": "Fernando de Noronha",
    "milao": "Milão", "amsterda": "Amsterdã", "montevideu": "Montevidéu", "bogota": "Bogotá",
    "cidade do mexico": "Cidade do México", "toquio": "Tóquio", "nova york": "Nova York", "punta cana": "Punta Cana",
}
MESES = {"jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6, "jul": 7, "ago": 8, "set": 9, "out": 10,
         "nov": 11, "dez": 12}

PALAVRAS_VOO = r"\b(passage(m|ns)|voos?|aere[oa]s?|avi[aã]o|ida e volta|so ida)\b"
PALAVRAS_HOTEL = r"\b(hote(l|is)|pousadas?|hospedage(m|ns)|resorts?|hostels?|chales?|airbnb|diarias?|pernoite)\b"


class Pedido(BaseModel):
    tipo: str  # "voo", "hospedagem" ou "produto"
    texto: str
    origem: str = ""
    destino: str = ""
    nome_origem: str = ""
    nome_destino: str = ""
    ida: Optional[date] = None
    volta: Optional[date] = None
    adultos: int = 1
    local: str = ""
    noites: int = 0
    termo: str = ""
    preco_max: Optional[float] = None
    faltando: List[str] = []  # o que precisa perguntar ao usuário


def _datas(texto: str, hoje: date) -> List[date]:
    """Acha datas como 20/12, 20/12/2026, 20-12 ou '20 de dezembro', na ordem em que aparecem."""
    achadas = []
    padrao = r"\b(\d{1,2})\s*(?:/|-|\.)\s*(\d{1,2})(?:\s*(?:/|-|\.)\s*(\d{2,4}))?\b|\b(\d{1,2})\s+de\s+([a-z]{3})[a-z]*(?:\s+de\s+(\d{4}))?"
    for m in re.finditer(padrao, texto):
        try:
            if m.group(1):
                dia, mes, ano = int(m.group(1)), int(m.group(2)), m.group(3)
            else:
                dia, mes, ano = int(m.group(4)), MESES.get(m.group(5)), m.group(6)
                if not mes:
                    continue
            if ano:
                ano = int(ano) + (2000 if len(ano) == 2 else 0)
                d = date(ano, mes, dia)
            else:
                d = date(hoje.year, mes, dia)
                if d < hoje:
                    d = date(hoje.year + 1, mes, dia)
            achadas.append(d)
        except ValueError:
            continue
    return achadas


def _aeroportos(texto: str) -> List[Tuple[str, str, int]]:
    """Acha cidades e códigos de aeroporto (ex.: GYN) na ordem em que aparecem: (códigos, nome, posição).
    `texto` já vem sem acentos, mas com as maiúsculas originais."""
    minusculo = texto.lower()
    achados = []
    ocupado = set()
    for cidade in sorted(AEROPORTOS, key=len, reverse=True):  # "sao paulo" antes de "sp"
        for m in re.finditer(rf"\b{re.escape(cidade)}\b", minusculo):
            if any(i in ocupado for i in range(m.start(), m.end())):
                continue
            ocupado.update(range(m.start(), m.end()))
            achados.append((AEROPORTOS[cidade], NOMES.get(cidade, cidade.title()), m.start()))
    for m in re.finditer(r"\b[A-Z]{3}\b", texto):  # código escrito em maiúsculas
        if not any(i in ocupado for i in range(m.start(), m.end())):
            achados.append((m.group(), m.group(), m.start()))
    return sorted(achados, key=lambda a: a[2])


def _numero(texto: str) -> float:
    texto = texto.replace(".", "").replace(",", ".") if "," in texto else texto.replace(".", "")
    return float(texto)


def interpretar(pedido: str, hoje: Optional[date] = None) -> Pedido:
    hoje = hoje or date.today()
    original = pedido.strip()
    # sem acentos; uma cópia mantém as maiúsculas para reconhecer códigos como GYN
    com_maiusculas = "".join(c for c in unicodedata.normalize("NFD", original) if unicodedata.category(c) != "Mn")
    texto = com_maiusculas.lower()

    preco_max = None
    m = re.search(r"\b(?:ate|max(?:imo)?|abaixo de|menos de)\s*(?:r\$\s*)?(\d[\d\.,]*)", texto)
    if m:
        preco_max = _numero(m.group(1))
    adultos = 0
    m = re.search(r"\b(\d+)\s*(adultos?|pessoas?|passageiros?|hospedes?)\b", texto)
    if m:
        adultos = int(m.group(1))
    datas = _datas(texto, hoje)

    if re.search(PALAVRAS_HOTEL, texto):
        p = Pedido(tipo="hospedagem", texto=original, adultos=adultos or 2, preco_max=preco_max)
        noites = re.search(r"\b(\d+)\s*(noites?|diarias?|dias?)\b", texto)
        if datas:
            p.ida = datas[0]
            if len(datas) > 1 and datas[1] > datas[0]:
                p.volta = datas[1]
            else:
                p.volta = datas[0] + timedelta(days=int(noites.group(1)) if noites else 2)
            p.noites = (p.volta - p.ida).days
        else:
            p.faltando.append("a data de entrada (ex.: 15/11)")
        local = re.sub(r"\b(\d{1,2}\s*(/|-|\.)\s*\d{1,2}((/|-|\.)\s*\d{2,4})?|\d{1,2}\s+de\s+\w+(\s+de\s+\d{4})?)\b", " ", original, flags=re.I)
        local = re.sub(r"\b(\d+\s*(noites?|di[aá]rias?|dias?|adultos?|pessoas?|h[oó]spedes?)|at[eé]\s*(r\$)?\s*[\d\.,]+|a|at[eé]|de|para|por)\b", " ", local, flags=re.I)
        p.local = re.sub(r"\s+", " ", local).strip(" ,.-")
        if not re.search(r"\bem\b", p.local, flags=re.I) and len(p.local.split()) > 1:
            palavras = p.local.split()
            p.local = f"{palavras[0]} em {' '.join(palavras[1:])}"
        return p

    cidades = _aeroportos(com_maiusculas)
    if re.search(PALAVRAS_VOO, texto) or (len(cidades) >= 2 and datas):
        p = Pedido(tipo="voo", texto=original, adultos=adultos or 1, preco_max=preco_max)
        if len(cidades) >= 2:
            # A palavra antes da cidade manda: "para X" = destino, "de X"/"saindo de X" = origem.
            origem = destino = None
            for c in cidades:
                antes = texto[:c[2]].rstrip()
                if re.search(r"\b(para|pra|p/|destino|ate)$", antes) and not destino:
                    destino = c
                elif re.search(r"\b(de|saindo de|partindo de|desde|origem)$", antes) and not origem:
                    origem = c
            resto = [c for c in cidades if c not in (origem, destino)]
            origem = origem or resto.pop(0)
            destino = destino or resto.pop(0)
            (p.origem, p.nome_origem, _), (p.destino, p.nome_destino, _) = origem, destino
        else:
            p.faltando.append("a cidade de origem e a de destino (ex.: goiânia para recife)")
        if datas:
            p.ida = datas[0]
            if len(datas) > 1 and datas[1] > datas[0]:
                p.volta = datas[1]
            else:
                dias = re.search(r"\b(\d+)\s*dias?\b", texto)
                if dias:
                    p.volta = p.ida + timedelta(days=int(dias.group(1)))
        else:
            p.faltando.append("a data de ida (ex.: 20/12, ou 20/12 a 27/12 para ida e volta)")
        return p

    termo = re.sub(r"\b(ate|max(imo)?|abaixo de|menos de)\s*(r\$\s*)?\d[\d\.,]*", " ", texto)
    termo = re.sub(r"\b(quanto custa|preco d[eoa]s?|promocao d[eoa]s?|procurar|pesquisar|buscar|comprar|quero)\b", " ", termo)
    termo = re.sub(r"\s+", " ", termo).strip(" ,.-?")
    return Pedido(tipo="produto", texto=original, termo=termo, preco_max=preco_max,
                  faltando=[] if termo else ["o que você quer pesquisar"])
