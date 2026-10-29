from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class SearchConfig(BaseModel):
    termos: List[str]
    preco_min: float = Field(0, ge=0)
    preco_max: float = Field(10000, gt=0)
    desconto_min: int = Field(20, ge=0, le=100)
    intervalo_minutos: int = Field(720, ge=5)


class Produto(BaseModel):
    titulo: str
    preco: float
    preco_original: Optional[float] = None
    desconto: int = 0
    link: str
    imagem: str = ""
    plataforma: str
    avaliacao: float = 0
    vendidos: int = 0
    loja: str = ""


class Comparativo(BaseModel):
    termo: str
    melhor_oferta: Produto
    todas_ofertas: List[Produto]
    economia: float


class ResultadoBusca(BaseModel):
    produtos: List[Produto]
    avisos: List[str] = []


class TrechoVoo(BaseModel):
    companhia: str = ""
    saida: str = ""
    chegada: str = ""
    horario_saida: str = ""


class Voo(BaseModel):
    preco: float
    companhia: str
    escalas: int = 0
    duracao_min: int = 0
    trechos: List[TrechoVoo] = []


class ResultadoVoos(BaseModel):
    voos: List[Voo]
    nivel_preco: str = ""  # "low", "typical" ou "high", segundo o Google
    faixa_tipica: Optional[List[float]] = None
    historico: List[List[float]] = []  # [timestamp, menor preço] dos últimos ~60 dias, segundo o Google
    link: str = ""


class Hospedagem(BaseModel):
    nome: str
    diaria: float
    total: Optional[float] = None
    nota: float = 0
    avaliacoes: int = 0
    tipo: str = ""
    link: str = ""
    imagem: str = ""
    oferta: str = ""  # ex.: "22% abaixo do normal", quando o Google informa


class Anuncio(BaseModel):
    titulo: str
    link: str
    resumo: str = ""
    fonte: str = ""
    data: str = ""
    publicado: Optional[datetime] = None
