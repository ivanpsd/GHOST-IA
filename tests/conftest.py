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
    from ghost.nucleo import painel, preferencias
    monkeypatch.setattr(preferencias, "ARQUIVO", str(tmp_path / "preferencias.json"))
    monkeypatch.setattr(preferencias, "_cache", None)
    monkeypatch.setattr(painel, "ARQ_CELULAR", str(tmp_path / "celular.json"))
    monkeypatch.setattr(painel, "PASTA_EXPORTAR", str(tmp_path / "relatorios"))
    monkeypatch.setattr(painel, "PASTA_DEMO", str(tmp_path / "demo"))
    monkeypatch.setattr(painel, "_clima", lambda: "")
