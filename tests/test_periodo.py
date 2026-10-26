"""Períodos falados -> datas (relatórios com 'Da Data' / 'Até a Data')."""
from datetime import date

import pytest

from ghost.automacao import periodo

HOJE = date(2026, 10, 27)          # terça-feira


@pytest.mark.parametrize("frase,esperado", [
    ("relatório de faturamento do mês passado", (date(2026, 9, 1), date(2026, 9, 30))),
    ("faturamento por cliente de 01/10 a 15/10", (date(2026, 10, 1), date(2026, 10, 15))),
    ("de 01/10/2026 até 15/10/2026", (date(2026, 10, 1), date(2026, 10, 15))),
    ("de 1 a 15 de outubro", (date(2026, 10, 1), date(2026, 10, 15))),
    ("do dia 5 até o dia 20", (date(2026, 10, 5), date(2026, 10, 20))),
    ("do dia 5 até hoje", (date(2026, 10, 5), HOJE)),
    ("de 20 de setembro a 10 de outubro", (date(2026, 9, 20), date(2026, 10, 10))),
    ("ontem", (date(2026, 10, 26), date(2026, 10, 26))),
    ("hoje", (HOJE, HOJE)),
    ("semana passada", (date(2026, 10, 19), date(2026, 10, 25))),
    ("desta semana", (date(2026, 10, 26), HOJE)),
    ("deste mês", (date(2026, 10, 1), HOJE)),
    ("últimos 7 dias", (date(2026, 10, 21), HOJE)),
    ("outubro", (date(2026, 10, 1), HOJE)),
    ("de novembro", (date(2025, 11, 1), date(2025, 11, 30))),      # novembro ainda não chegou: o do ano passado
    ("dezembro de 2025", (date(2025, 12, 1), date(2025, 12, 31))),
    ("de 15/12 a 10/01", (date(2025, 12, 15), date(2026, 1, 10))),
])
def test_periodos(frase, esperado):
    assert periodo.interpretar(frase, HOJE) == esperado


def test_sem_periodo():
    assert periodo.interpretar("relatório de faturamento por cliente", HOJE) is None


def test_formato_e_papel():
    assert periodo.formato_de("01/10/2026") == "%d/%m/%Y" and periodo.formato_de("011026") == "%d%m%y"
    assert periodo.parece_data("26/10/2026") and not periodo.parece_data("000371") and not periodo.parece_data("99/99/2026")
    assert periodo.papel("Da Data ?", 0) == "inicio" and periodo.papel("Até a Data ?", 1) == "fim"
    assert periodo.papel("Emissão", 1) == "fim"
