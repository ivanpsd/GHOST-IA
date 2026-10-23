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
