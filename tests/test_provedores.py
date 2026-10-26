"""Fila de modelos gratuitos e ferramentas enviadas por pedido."""
import json
import sys
import types

import pytest

from ghost.ia import provedores


def test_fila_so_com_quem_tem_chave(monkeypatch):
    for var, _ in provedores.EXTRAS.values():
        monkeypatch.delenv(var, raising=False)
    provedores.iniciar(object())
    assert provedores.rotas() == [("groq", "openai/gpt-oss-120b"), ("groq", "openai/gpt-oss-20b")]
    pytest.importorskip("openai")
    monkeypatch.setenv("CEREBRAS_API_KEY", "teste")
    monkeypatch.setenv("CEREBRAS_MODELO", "outro-modelo")
    assert provedores.iniciar(object()) == ["groq", "cerebras"]
    assert provedores.rotas()[1] == ("cerebras", "outro-modelo")
    assert provedores.parametros("mistral", "mistral-small-latest", "medium") == {}
    assert provedores.parametros("groq", "openai/gpt-oss-120b", "medium") == {"reasoning_effort": "medium"}


def test_ferramentas_por_pedido(monkeypatch):
    if "pyautogui" not in sys.modules:
        monkeypatch.setitem(sys.modules, "pyautogui", types.ModuleType("pyautogui"))
    from ghost.ia import ferramentas as f
    nomes = lambda lista: {x["function"]["name"] for x in lista}
    todas = nomes(f.TOOLS)
    assert set(f.SEMPRE) | set().union(*[g for _, g in f.GRUPOS]) == todas      # nenhuma ferramenta esquecida
    p = f.escolher("quanto produzimos ontem na planilha de produção")
    assert {"ver_planilha", "calcular_planilha"} <= nomes(p) and "olhar_camera" not in nomes(p)
    assert len(json.dumps(p)) < len(json.dumps(f.TOOLS)) * 0.6
    assert "criar_lembrete" in nomes(f.escolher("e amanhã?", anterior="me lembra às 15h de ligar"))
    assert nomes(f.escolher("oi")) == todas                                     # vago demais: todas
