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


def _post(url, corpo=None):
    dados = json.dumps(corpo or {}).encode()
    req = urllib.request.Request(url, data=dados, method="POST", headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=5)


def test_app_do_celular(tmp_path, monkeypatch):
    pytest.importorskip("segno")
    monkeypatch.setattr(painel, "ARQ_CELULAR", str(tmp_path / "celular.json"))
    monkeypatch.setattr(painel, "PORTA_CELULAR", 0)
    monkeypatch.setattr(painel.preferencias, "definir", lambda *a: None)
    monkeypatch.setattr(painel, "_coletar", lambda: None)
    painel.iniciar(abrir=False)
    recebidos = []
    monkeypatch.setattr(painel, "_entregar", recebidos.append)
    try:
        r = painel.celular_ativar()
        assert r["qr_svg"].lstrip().startswith("<svg") and "/celular?t=" in r["endereco"]
        porta = painel._servidor_celular.server_address[1]
        base = f"http://127.0.0.1:{porta}/"
        token = painel._token_celular()
        with urllib.request.urlopen(f"{base}celular?t={token}", timeout=5) as resp:
            html = resp.read().decode()
        assert token in html and "__GHOST_TOKEN__" not in html
        with _post(f"{base}comando?t={token}", {"texto": "resumo do dia"}) as resp:
            assert json.loads(resp.read())["ok"]
        assert recebidos == [{"texto": "resumo do dia", "origem": "celular"}]
        assert painel.foto()["celular"][-1]["texto"] == "resumo do dia"
        with pytest.raises(urllib.error.HTTPError) as erro:             # exportar só pelo PC
            _post(f"{base}exportar?t={token}")
        assert erro.value.code == 403
        with pytest.raises(urllib.error.HTTPError):                    # chave da sessão do PC não vale na rede
            urllib.request.urlopen(f"{base}estado?t={painel._token}", timeout=5)
        antigo = token
        painel.celular_ativar(trocar=True)
        with pytest.raises(urllib.error.HTTPError):                    # link antigo para de funcionar
            urllib.request.urlopen(f"{base}estado?t={antigo}", timeout=5)
    finally:
        painel.celular_desativar()


def test_criar_demonstracao(tmp_path, monkeypatch):
    monkeypatch.setattr(painel, "PASTA_DEMO", str(tmp_path))
    caminho = painel.criar_demonstracao(abrir=False)
    html = open(caminho, encoding="utf-8").read()
    assert "GhostNucleo" in html and 'src="nucleo.js"' not in html and "__GHOST_TOKEN__" in html
    assert (tmp_path / "celular.html").exists() and (tmp_path / "icone-192.png").exists()
