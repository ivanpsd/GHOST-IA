"""Configuração comum dos testes.

Os testes NÃO tocam nos seus dados reais: cada um que grava algo aponta o módulo para uma pasta temporária.
Rodar: testar.bat   (ou .\\.venv\\Scripts\\python.exe -m pytest)
"""
import os
import sys

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

windows = pytest.mark.skipif(os.name != "nt", reason="só no Windows (bibliotecas de áudio/teclado)")


@pytest.fixture(autouse=True)
def _dados_isolados(tmp_path, monkeypatch):
    """Nenhum teste grava na pasta dados/ de verdade (preferências, celular) nem consulta o clima na internet."""
    from ghost.nucleo import celular, painel, preferencias
    monkeypatch.setattr(preferencias, "ARQUIVO", str(tmp_path / "preferencias.json"))
    monkeypatch.setattr(preferencias, "_cache", None)
    monkeypatch.setattr(celular, "ARQUIVO", str(tmp_path / "celular.json"))
    monkeypatch.setattr(painel, "PASTA_EXPORTAR", str(tmp_path / "relatorios"))
    monkeypatch.setattr(painel, "PASTA_DEMO", str(tmp_path / "demo"))
    monkeypatch.setattr(painel, "_clima", lambda: "")
    from ghost.automacao import demonstracao
    from ghost.ia import skills
    monkeypatch.setattr(skills, "ARQUIVO", str(tmp_path / "skills.json"))
    monkeypatch.setattr(demonstracao, "PASTA", str(tmp_path / "skills"))
    monkeypatch.setattr(demonstracao, "PASTA_RASCUNHO", str(tmp_path / "skills" / "rascunho"))
