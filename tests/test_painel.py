"""Tela de indicadores: contadores, foto do momento, exportação e servidor local."""
import json
import urllib.request

import pytest

from ghost.nucleo import painel


def test_contadores_e_falas():
    painel.contar("teste_x")
    painel.contar("teste_x", 2)
    painel.fala("voce", "abre o excel")
    painel.estado("pensando", "Você: abre o excel")
    painel.medir("transcricao", 0.4)
    f = painel.foto()
    assert f["contadores"]["teste_x"] == 3
    assert f["falas"]["voce"] == "abre o excel"
    assert f["estado"]["nome"] == "pensando"
    assert 0.4 in f["medidas"]["transcricao"]
    json.dumps(f, default=str)                        # a janela recebe isso como JSON


def test_exportar_gera_excel(tmp_path, monkeypatch):
    openpyxl = pytest.importorskip("openpyxl")
    monkeypatch.setattr(painel, "PASTA_EXPORTAR", str(tmp_path))
    painel.evento("teste de exportação", "acao")
    caminho = painel.exportar()
    wb = openpyxl.load_workbook(caminho)
    assert wb.sheetnames == ["Resumo", "Histórico", "Eventos", "Rotina de hoje"]
    assert wb["Resumo"]["A1"].value == "Indicador"


def test_servidor_exige_token(monkeypatch):
    monkeypatch.setattr(painel, "PORTA", 0)
    monkeypatch.setattr(painel, "_coletar", lambda: None)
    painel.iniciar(abrir=False)
    base = painel.endereco().split("?")[0]
    with pytest.raises(urllib.error.HTTPError) as erro:
        urllib.request.urlopen(base + "estado?t=errado", timeout=5)
    assert erro.value.code == 403
    with urllib.request.urlopen(painel.endereco().replace("/?", "/estado?"), timeout=5) as r:
        assert "estado" in json.loads(r.read())
    with urllib.request.urlopen(painel.endereco(), timeout=5) as r:
        html = r.read().decode()
    assert "__GHOST_TOKEN__" not in html and html.startswith("<!doctype html>")


def test_criar_demonstracao(tmp_path, monkeypatch):
    monkeypatch.setattr(painel, "PASTA_DEMO", str(tmp_path))
    caminho = painel.criar_demonstracao(abrir=False)
    html = open(caminho, encoding="utf-8").read()
    assert "GhostNucleo" in html and 'src="nucleo.js"' not in html and "__GHOST_TOKEN__" in html
    assert (tmp_path / "celular.html").exists() and (tmp_path / "icone-192.png").exists()
