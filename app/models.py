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
