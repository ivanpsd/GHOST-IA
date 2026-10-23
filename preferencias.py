"""
GHOST - Preferências de comportamento que você muda por voz.
Ex.: "a partir de agora, diga 'Olá, Ivan' quando eu te chamar".
Arquivo: preferencias.json (fora do Git).
"""
import os
import json
import arquivo

PASTA_GHOST = os.path.dirname(os.path.abspath(__file__))
ARQUIVO = os.path.join(PASTA_GHOST, "preferencias.json")
PADRAO = {"saudacao": "Olá, Ivan.", "cidade": "Santana de Parnaíba", "personalidade": "jarvis"}


def carregar():
    try:
        with open(ARQUIVO, "r", encoding="utf-8") as f:
            return {**PADRAO, **json.load(f)}
    except Exception:
        return dict(PADRAO)


def definir(chave, valor):
    dados = carregar()
    dados[chave] = valor
    arquivo.salvar_json(ARQUIVO, dados)
