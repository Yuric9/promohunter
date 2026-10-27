from datetime import date

import pytest

from app.interpretador import interpretar

HOJE = date(2026, 10, 27)


def test_voo_ida_e_volta_com_cidades():
    p = interpretar("passagem goiânia recife 20/12 a 27/12", HOJE)
    assert p.tipo == "voo" and (p.origem, p.destino) == ("GYN", "REC")
    assert (p.ida, p.volta, p.adultos, p.faltando) == (date(2026, 12, 20), date(2026, 12, 27), 1, [])


def test_voo_com_para_e_codigos_e_pessoas():
    p = interpretar("Voo para Salvador saindo de Brasília dia 05/01/2027, 2 pessoas", HOJE)
    assert (p.origem, p.destino, p.ida, p.volta, p.adultos) == ("BSB", "SSA", date(2027, 1, 5), None, 2)
    p = interpretar("GYN REC 20/12 até 1500", HOJE)
    assert (p.tipo, p.origem, p.destino, p.preco_max) == ("voo", "GYN", "REC", 1500)


def test_voo_data_por_extenso_e_duracao():
    p = interpretar("passagens de são paulo para lisboa 10 de março 15 dias", HOJE)
    assert (p.origem, p.destino) == ("GRU,CGH,VCP", "LIS")
    assert (p.ida, p.volta) == (date(2027, 3, 10), date(2027, 3, 25))  # março já passou em 2026 → 2027


def test_voo_sem_data_pergunta():
    p = interpretar("passagem goiania recife", HOJE)
    assert p.tipo == "voo" and any("data" in f for f in p.faltando)


def test_hospedagem():
    p = interpretar("pousada em Pirenópolis 15/11 2 noites", HOJE)
    assert p.tipo == "hospedagem" and p.local == "pousada em Pirenópolis"
    assert (p.ida, p.volta, p.noites, p.adultos) == (date(2026, 11, 15), date(2026, 11, 17), 2, 2)
    p = interpretar("hotel caldas novas 20/11 a 23/11 4 pessoas até 300", HOJE)
    assert p.local == "hotel em caldas novas" and p.noites == 3 and p.adultos == 4 and p.preco_max == 300


def test_hospedagem_sem_data_pergunta():
    assert interpretar("hotel em gramado", HOJE).faltando


@pytest.mark.parametrize("texto,termo,maximo", [
    ("iphone 17 128gb", "iphone 17 128gb", None),
    ("quanto custa uma air fryer até R$ 400", "uma air fryer", 400),
    ("PS5 slim até 3.500", "ps5 slim", 3500),
])
def test_produto(texto, termo, maximo):
    p = interpretar(texto, HOJE)
    assert (p.tipo, p.termo, p.preco_max) == ("produto", termo, maximo)
