"""App do celular: pareamento de uso único, PIN, bloqueio, sessão e confirmação de ações sensíveis."""
import json
import time
import urllib.error
import urllib.request

import pytest

from ghost.nucleo import celular


@pytest.fixture
def app(monkeypatch):
    pytest.importorskip("segno")
    monkeypatch.setattr(celular, "PORTA", 0)
    monkeypatch.setattr(celular, "tailscale_nome", lambda: None)
    monkeypatch.setattr(celular, "rede_local_segura", lambda: True)
    monkeypatch.setattr(celular, "_sessoes", {})
    monkeypatch.setattr(celular, "_erros", {})
    recebidos = []
    monkeypatch.setattr(celular, "_entregar", recebidos.append)
    monkeypatch.setattr(celular, "_avisar", None)
    r = celular.ativar()
    base = f"http://127.0.0.1:{celular._servidor.server_address[1]}/"
    yield base, r, recebidos
    celular.desativar()


def pedir(base, rota, corpo=None, sessao=None, metodo=None):
    dados = None if corpo is None else json.dumps(corpo).encode()
    req = urllib.request.Request(base + rota, data=dados, method=metodo or ("POST" if corpo is not None else "GET"),
                                 headers={"Content-Type": "application/json",
                                          **({"Authorization": f"Bearer {sessao}"} if sessao else {})})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_pareamento_pin_e_sessao(app):
    base, r, recebidos = app
    assert r["modo"] == "rede local" and r["qr_svg"].lstrip().startswith("<svg") and len(r["codigo"]) == 7
    codigo = r["codigo"]
    # sem sessão, nada
    assert pedir(base, "api/estado")[0] == 401
    assert pedir(base, "api/comando", {"texto": "oi"})[0] == 401
    # 1º pareamento cria o PIN (os dois precisam ser iguais)
    st, j = pedir(base, "api/parear", {"codigo": codigo, "nome": "Teste", "pin": "123456", "pin_confirmacao": "654321"})
    assert st == 400 and "iguais" in j["erro"]
    st, j = pedir(base, "api/parear", {"codigo": codigo.lower(), "nome": "Teste", "pin": "123456", "pin_confirmacao": "123456"})
    assert st == 200 and j["aparelho_token"] and j["sessao"]
    # o código é de uso único
    st, _ = pedir(base, "api/parear", {"codigo": codigo, "nome": "Outro", "pin": "123456"})
    assert st == 400
    # com sessão: estado e pedidos
    st, est = pedir(base, "api/estado", sessao=j["sessao"])
    assert st == 200 and est["aparelho"] == "Teste" and "celular" in est
    assert pedir(base, "api/comando", {"texto": "resumo do dia"}, sessao=j["sessao"])[0] == 200
    assert recebidos[-1] == {"texto": "resumo do dia", "origem": "celular", "aparelho": "Teste"}
    # sair encerra a sessão; o PIN abre outra
    pedir(base, "api/sair", {}, sessao=j["sessao"])
    assert pedir(base, "api/estado", sessao=j["sessao"])[0] == 401
    st, k = pedir(base, "api/entrar", {"aparelho_token": j["aparelho_token"], "pin": "123456"})
    assert st == 200 and pedir(base, "api/estado", sessao=k["sessao"])[0] == 200


def test_pin_errado_bloqueia_e_remove(app):
    base, r, _ = app
    _, j = pedir(base, "api/parear", {"codigo": r["codigo"], "nome": "X", "pin": "111111", "pin_confirmacao": "111111"})
    for _ in range(4):
        assert "Restam" in pedir(base, "api/entrar", {"aparelho_token": j["aparelho_token"], "pin": "000000"})[1]["erro"]
    assert "bloqueado" in pedir(base, "api/entrar", {"aparelho_token": j["aparelho_token"], "pin": "000000"})[1]["erro"]
    # bloqueado: nem o PIN certo entra
    assert "Bloqueado" in pedir(base, "api/entrar", {"aparelho_token": j["aparelho_token"], "pin": "111111"})[1]["erro"]
    celular._erros[next(iter(celular._erros))]["ate"] = 0          # passa o tempo do bloqueio
    assert pedir(base, "api/entrar", {"aparelho_token": j["aparelho_token"], "pin": "111111"})[0] == 200


def test_codigo_vence_e_limita_tentativas(app):
    base, r, _ = app
    for _ in range(5):
        assert pedir(base, "api/parear", {"codigo": "ZZZZZZ", "pin": "123456", "pin_confirmacao": "123456"})[0] == 400
    st, j = pedir(base, "api/parear", {"codigo": r["codigo"], "pin": "123456", "pin_confirmacao": "123456"})
    assert st == 400 and "Tentativas" in j["erro"]                 # 6ª tentativa: código cancelado
    p = celular.novo_codigo()
    celular._pareamento["expira"] = time.time() - 1
    assert "vencido" in pedir(base, "api/parear", {"codigo": p["codigo"], "pin": "123456", "pin_confirmacao": "123456"})[1]["erro"]


def test_remover_aparelho_derruba_a_sessao(app):
    base, r, _ = app
    _, j = pedir(base, "api/parear", {"codigo": r["codigo"], "nome": "Perdido", "pin": "222222", "pin_confirmacao": "222222"})
    aparelho = celular.aparelhos()[0]
    assert celular.remover(aparelho["id"])
    assert pedir(base, "api/estado", sessao=j["sessao"])[0] == 401
    assert "pareado" in pedir(base, "api/entrar", {"aparelho_token": j["aparelho_token"], "pin": "222222"})[1]["erro"]


def test_pin_e_chaves_nao_ficam_em_texto(app):
    base, r, _ = app
    _, j = pedir(base, "api/parear", {"codigo": r["codigo"], "nome": "A", "pin": "987654", "pin_confirmacao": "987654"})
    conteudo = open(celular.ARQUIVO, encoding="utf-8").read()
    assert "987654" not in conteudo and j["aparelho_token"] not in conteudo


def test_rede_publica_nao_liga(monkeypatch):
    monkeypatch.setattr(celular, "tailscale_nome", lambda: None)
    monkeypatch.setattr(celular, "rede_local_segura", lambda: False)
    with pytest.raises(celular.ErroCelular, match="Privada"):
        celular.ativar()
    assert celular._servidor is None
