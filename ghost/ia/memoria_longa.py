"""
GHOST - Memória de longo prazo pesquisável pelo SENTIDO (local e gratuita).

Toda conversa fica guardada com data e hora em dados/historico_completo.jsonl, junto com um
"vetor de sentido" (modelo multilíngue rodando no PC, sem internet depois de baixado).
Assim a IA pode buscar: "o que eu te falei semana passada sobre o fornecedor X?",
mesmo que você não use as mesmas palavras. Arquivos pessoais, fora do Git.

Desempenho: o histórico fica em memória e só as linhas novas são lidas e vetorizadas.
A busca usa os vetores já prontos (não espera a indexação nem o modelo carregar na hora).
"""
import os
import threading
import time
from datetime import datetime

import numpy as np

from ghost.nucleo import arquivo, caminhos

ARQ_TEXTO = caminhos.dado("historico_completo.jsonl")
ARQ_VETORES = caminhos.dado("historico_vetores.npy")
MODELO = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
PASTA_MODELO = caminhos.modelo("embeddings")
DIM = 384
SIMILARIDADE_MINIMA = 0.25

_trava = threading.RLock()           # protege _itens/_vetores
_trava_modelo = threading.Lock()     # carregar o modelo (lento) não bloqueia quem só lê
_trava_sync = threading.Lock()       # uma sincronização por vez
_modelo = None
_itens = None                        # lista de trocas (cache)
_vetores = None                      # np.ndarray (n, DIM), alinhado com _itens[:n]


def _embed(textos):
    global _modelo
    with _trava_modelo:
        if _modelo is None:
            from fastembed import TextEmbedding
            _modelo = TextEmbedding(MODELO, cache_dir=PASTA_MODELO)
        v = np.array(list(_modelo.embed(textos)), dtype=np.float32)
    return v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-9)


def _texto(item):
    return f"Ivan: {item['usuario']}\nGhost: {item['ghost']}"


def _garantir_cache():
    global _itens, _vetores
    with _trava:
        if _itens is None:
            _itens = [i for i in arquivo.ler_jsonl(ARQ_TEXTO) if i.get("usuario") and i.get("ghost")]
            try:
                v = np.load(ARQ_VETORES)
                _vetores = v[: len(_itens)] if v.ndim == 2 and v.shape[1] == DIM else np.zeros((0, DIM), np.float32)
            except (FileNotFoundError, ValueError, OSError):
                _vetores = np.zeros((0, DIM), np.float32)
        return _itens, _vetores


def _sincronizar():
    """Calcula os vetores que faltam (só os novos) e grava."""
    global _vetores
    with _trava_sync:
        itens, vet = _garantir_cache()
        with _trava:
            faltam = itens[len(vet):]
            ini = len(vet)
        if not faltam:
            return
        novos = _embed([_texto(i) for i in faltam])
        with _trava:
            if len(_vetores) != ini:          # alguém mudou no meio (não deveria): recomeça na próxima
                return
            _vetores = np.vstack([_vetores, novos]) if len(_vetores) else novos
            copia = _vetores.copy()
        tmp = ARQ_VETORES + ".tmp.npy"
        np.save(tmp, copia)
        os.replace(tmp, ARQ_VETORES)


def _sincronizar_seguro():
    try:
        _sincronizar()
    except Exception as e:
        print(f"\n[MEMÓRIA LONGA]: não consegui indexar ({e}).")


def adicionar(usuario, ghost, quando=None):
    """Guarda uma troca (o vetor é calculado em segundo plano)."""
    if not usuario or not ghost:
        return
    item = {"t": quando or time.time(), "usuario": str(usuario)[:1500], "ghost": str(ghost)[:1500]}
    arquivo.acrescentar_jsonl(ARQ_TEXTO, item)
    with _trava:
        if _itens is not None:
            _itens.append(item)
    threading.Thread(target=_sincronizar_seguro, daemon=True, name="memoria-longa").start()


def _data(s):
    return datetime.strptime(s[:10], "%Y-%m-%d").timestamp() if s else None


def buscar(pergunta, data_inicio="", data_fim="", quantidade=6):
    """Trocas mais parecidas com a pergunta (opcionalmente dentro de um período AAAA-MM-DD)."""
    itens, _ = _garantir_cache()
    threading.Thread(target=_sincronizar_seguro, daemon=True).start()     # indexa o atraso em segundo plano
    with _trava:
        itens = list(itens)
        vet = _vetores.copy()
    if not itens:
        return "Ainda não há conversas guardadas na memória de longo prazo."
    try:
        ini = _data(data_inicio)
        fim = _data(data_fim) + 86400 if data_fim else None
    except ValueError:
        return "Data inválida: use o formato AAAA-MM-DD."
    idx = [i for i, it in enumerate(itens) if (ini is None or it["t"] >= ini) and (fim is None or it["t"] < fim)]
    if not idx:
        return "Nenhuma conversa guardada nesse período."
    quantidade = max(1, min(int(quantidade or 6), 20))
    if (pergunta or "").strip():
        com_vetor = [i for i in idx if i < len(vet)]
        if not com_vetor:
            return "Ainda estou indexando as conversas; tente de novo em alguns segundos."
        notas = vet[com_vetor] @ _embed([pergunta])[0]
        ordem = [com_vetor[i] for i in np.argsort(-notas)[:quantidade] if notas[i] > SIMILARIDADE_MINIMA]
    else:
        ordem = idx[-quantidade:]
    if not ordem:
        return "Não encontrei nada parecido nas conversas guardadas."
    ordem.sort(key=lambda i: itens[i]["t"])
    return "\n".join(f"[{datetime.fromtimestamp(itens[i]['t']):%d/%m/%Y %H:%M}] Ivan: {itens[i]['usuario'][:300]} | "
                     f"Ghost: {itens[i]['ghost'][:300]}" for i in ordem)


def importar_antigos(lista):
    """Importa uma única vez trocas antigas [{'t','usuario','ghost'}] (ex.: conversa_recente.json)."""
    if os.path.exists(ARQ_TEXTO):
        return 0
    n = 0
    for it in lista:
        if it.get("usuario") and it.get("ghost"):
            arquivo.acrescentar_jsonl(ARQ_TEXTO, {"t": it.get("t", time.time()), "usuario": it["usuario"],
                                                  "ghost": it["ghost"]})
            n += 1
    threading.Thread(target=_sincronizar_seguro, daemon=True).start()
    return n
