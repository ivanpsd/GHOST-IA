"""
GHOST - Memória de longo prazo pesquisável pelo SENTIDO (local e gratuita).

Toda conversa fica guardada com data e hora em historico_completo.jsonl, junto com um
"vetor de sentido" (modelo multilíngue rodando no PC, sem internet depois de baixado).
Assim a IA pode buscar: "o que eu te falei semana passada sobre o fornecedor X?",
mesmo que você não use as mesmas palavras. Arquivos pessoais, fora do Git.
"""
import os
import json
import time
import threading
from datetime import datetime

import numpy as np

PASTA = os.path.dirname(os.path.abspath(__file__))
ARQ_TEXTO = os.path.join(PASTA, "historico_completo.jsonl")
ARQ_VETORES = os.path.join(PASTA, "historico_vetores.npy")
MODELO = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
PASTA_MODELO = os.path.join(PASTA, "modelos", "embeddings")

_trava = threading.RLock()
_modelo = None


def _embed(textos):
    global _modelo
    with _trava:
        if _modelo is None:
            from fastembed import TextEmbedding
            _modelo = TextEmbedding(MODELO, cache_dir=PASTA_MODELO)
        v = np.array(list(_modelo.embed(textos)), dtype=np.float32)
    return v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-9)


def _ler_textos():
    itens = []
    try:
        with open(ARQ_TEXTO, "r", encoding="utf-8") as f:
            for linha in f:
                if linha.strip():
                    itens.append(json.loads(linha))
    except FileNotFoundError:
        pass
    return itens


def _ler_vetores():
    try:
        return np.load(ARQ_VETORES)
    except Exception:
        return np.zeros((0, 384), np.float32)


def _sincronizar():
    """Garante um vetor por conversa (calcula os que faltam)."""
    with _trava:
        itens, vet = _ler_textos(), _ler_vetores()
        if len(vet) > len(itens):
            vet = vet[: len(itens)]
        if len(vet) < len(itens):
            novos = _embed([_texto(i) for i in itens[len(vet):]])
            vet = np.vstack([vet, novos]) if len(vet) else novos
            tmp = ARQ_VETORES + ".tmp.npy"
            np.save(tmp, vet)
            os.replace(tmp, ARQ_VETORES)
        return itens, vet


def _texto(item):
    return f"Ivan: {item['usuario']}\nGhost: {item['ghost']}"


def adicionar(usuario, ghost, quando=None):
    """Guarda uma troca (o vetor é calculado em segundo plano)."""
    if not usuario or not ghost:
        return
    item = {"t": quando or time.time(), "usuario": usuario[:1500], "ghost": ghost[:1500]}
    with _trava:
        with open(ARQ_TEXTO, "a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    threading.Thread(target=_sincronizar_seguro, daemon=True).start()


def _sincronizar_seguro():
    try:
        _sincronizar()
    except Exception as e:
        print(f"\n[MEMÓRIA LONGA]: não consegui indexar ({e}).")


def _data(s):
    return datetime.strptime(s[:10], "%Y-%m-%d").timestamp() if s else None


def buscar(pergunta, data_inicio="", data_fim="", quantidade=6):
    """Trocas mais parecidas com a pergunta (opcionalmente dentro de um período AAAA-MM-DD)."""
    itens, vet = _sincronizar()
    if not itens:
        return "Ainda não há conversas guardadas na memória de longo prazo."
    ini = _data(data_inicio)
    fim = _data(data_fim) + 86400 if data_fim else None
    idx = [i for i, it in enumerate(itens) if (ini is None or it["t"] >= ini) and (fim is None or it["t"] < fim)]
    if not idx:
        return "Nenhuma conversa guardada nesse período."
    if pergunta.strip():
        notas = vet[idx] @ _embed([pergunta])[0]
        ordem = [idx[i] for i in np.argsort(-notas)[: int(quantidade)] if notas[i] > 0.25]
    else:
        ordem = idx[-int(quantidade):]
    if not ordem:
        return "Não encontrei nada parecido nas conversas guardadas."
    ordem.sort(key=lambda i: itens[i]["t"])
    return "\n".join(f"[{datetime.fromtimestamp(itens[i]['t']):%d/%m/%Y %H:%M}] Ivan: {itens[i]['usuario'][:300]} | "
                     f"Ghost: {itens[i]['ghost'][:300]}" for i in ordem)


def importar_antigos(lista):
    """Importa uma única vez trocas antigas [{'t','usuario','ghost'}] (ex.: conversa_recente.json)."""
    if os.path.exists(ARQ_TEXTO):
        return 0
    with _trava:
        with open(ARQ_TEXTO, "w", encoding="utf-8") as f:
            for it in lista:
                if it.get("usuario") and it.get("ghost"):
                    f.write(json.dumps({"t": it.get("t", time.time()), "usuario": it["usuario"],
                                        "ghost": it["ghost"]}, ensure_ascii=False) + "\n")
    threading.Thread(target=_sincronizar_seguro, daemon=True).start()
    return len(lista)
