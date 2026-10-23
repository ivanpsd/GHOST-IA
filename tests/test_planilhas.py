import pandas as pd
import pytest

from ghost.automacao import planilhas


@pytest.fixture
def pasta(tmp_path, monkeypatch):
    monkeypatch.setattr(planilhas.preferencias, "carregar", lambda: {"pastas_planilhas": [str(tmp_path)]})
    monkeypatch.setattr(planilhas, "_indice", {"t": 0, "arquivos": []})
    (tmp_path / "Producao Outubro.csv").write_bytes(
        "Data;Produto;Quantidade;Código\n22/10/2026;Pão de Mel;1.234,5;10\n"
        "23/10/2026;Bolo;20,0;11\n2026-10-24;Pão de Mel;5;10\n".encode("cp1252"))
    return tmp_path


def test_encontra_pelo_nome_falado(pasta):
    assert planilhas.encontrar("planilha de produção").endswith("Producao Outubro.csv")
    assert planilhas.encontrar("planilha de férias") is None


def test_csv_brasileiro_cp1252_com_decimal_virgula(pasta):
    assert "1259.5" in planilhas.calcular("produção", operacao="soma", coluna_valor="quantidade")


def test_filtro_numerico_igual(pasta):
    r = planilhas.calcular("produção", filtros=[{"coluna": "codigo", "operador": "=", "valor": "10"}],
                           operacao="soma", coluna_valor="quantidade")
    assert "1239.5" in r and "2 linhas" in r


def test_filtro_de_datas_entre(pasta):
    r = planilhas.calcular("produção", filtros=[{"coluna": "data", "operador": "entre", "valor": "22/10/2026|23/10/2026"}],
                           agrupar_por="produto", coluna_valor="quantidade")
    assert "Bolo" in r and "2 linhas" in r


def test_operador_invalido_explica(pasta):
    with pytest.raises(ValueError, match="operador"):
        planilhas.calcular("produção", filtros=[{"coluna": "codigo", "operador": "~", "valor": "1"}])


def test_datas_seriais_do_excel():
    d = planilhas._datas(pd.Series([46317, 46318]))
    assert str(d.iloc[0].date()) == "2026-10-22"


def test_numero_brasileiro():
    assert planilhas._numero("1.234,5") == 1234.5
    assert planilhas._numero("12") == 12.0
    assert planilhas._numero("abc") is None


def test_cabecalho_nao_texto():
    assert planilhas._normalizar(2026) == "2026"
    assert planilhas._normalizar(None) == ""
