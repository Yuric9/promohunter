import math
from typing import List, Optional

from app.models import Comparativo, Produto


def score(p: Produto) -> float:
    """Nota de 0 a ~100: desconto pesa mais, depois vendas e avaliação."""
    vendas = min(math.log10(p.vendidos + 1) / 4, 1)  # 10 mil vendas = nota máxima
    avaliacao = p.avaliacao / 5
    return p.desconto * 0.7 + vendas * 20 + avaliacao * 10


def filtrar(produtos: List[Produto], desconto_min=0, preco_min=0.0, preco_max=math.inf) -> List[Produto]:
    return [p for p in produtos if p.desconto >= desconto_min and preco_min <= p.preco <= preco_max]


def rankear_melhores(produtos: List[Produto], desconto_min=0, preco_min=0.0, preco_max=math.inf) -> List[Produto]:
    return sorted(filtrar(produtos, desconto_min, preco_min, preco_max), key=score, reverse=True)


def comparar_termo(termo: str, produtos: List[Produto], desconto_min=20,
                   preco_min=0.0, preco_max=math.inf) -> Optional[Comparativo]:
    rank = rankear_melhores(produtos, desconto_min, preco_min, preco_max)
    if not rank:
        return None
    melhor = rank[0]
    economia = (melhor.preco_original - melhor.preco) if melhor.preco_original else 0.0
    return Comparativo(termo=termo, melhor_oferta=melhor, todas_ofertas=rank[:10], economia=round(economia, 2))
