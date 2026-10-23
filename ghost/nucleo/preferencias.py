"""
GHOST - Preferências de comportamento que você muda por voz.
Ex.: "a partir de agora, diga 'Olá, Ivan' quando eu te chamar".
Arquivo: dados/preferencias.json (fora do Git).

Fica em memória (leitura instantânea) e é gravado com trava: várias threads gravam aqui
(microfone, clima, comandos) e nenhuma alteração se perde.
"""
import copy
import threading

from ghost.nucleo import arquivo, caminhos

ARQUIVO = caminhos.dado("preferencias.json")
PADRAO = {"saudacao": "Olá, Ivan.", "cidade": "Santana de Parnaíba", "personalidade": "jarvis"}

_trava = threading.RLock()
_cache = None
_arquivo_ruim = False      # existe mas não foi lido: não gravar por cima


def _garantir():
    global _cache, _arquivo_ruim
    if _cache is None:
        try:
            _cache = {**PADRAO, **(arquivo.ler_json(ARQUIVO, {}) or {})}
        except arquivo.ArquivoCorrompido:
            _cache, _arquivo_ruim = dict(PADRAO), True
    return _cache


def carregar():
    with _trava:
        return copy.deepcopy(_garantir())


def definir(chave, valor):
    with _trava:
        dados = _garantir()
        if dados.get(chave) == valor:
            return
        dados[chave] = valor
        if _arquivo_ruim:
            print("\n[PREFERÊNCIAS]: arquivo original corrompido; alteração mantida só nesta sessão.")
            return
        arquivo.salvar_json(ARQUIVO, dados)
