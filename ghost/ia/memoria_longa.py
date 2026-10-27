"""
GHOST - Memória de longo prazo pesquisável (local, gratuita e LEVE).

Toda conversa fica guardada com data e hora em dados/historico_completo.jsonl. A busca é por PALAVRAS
(sem acento, sem maiúscula, aproximando variações: "fornecedor"/"fornecedores", "estoque"/"estocar"),
com peso maior para palavras raras (BM25). Antes usava um modelo de "sentido" que ocupava ~500 MB de RAM;
foi trocado em 27/10/2026 para economizar memória neste PC.
"""
import math
import os
import re
import threading
import time
import unicodedata
from collections import Counter
from datetime import datetime

from ghost.nucleo import arquivo, caminhos

ARQ_TEXTO = caminhos.dado("historico_completo.jsonl")
RAIZ = 5                 # "fornecedores" e "fornecedor" viram "forne": aproxima plural, gênero e verbo
PARAR = set("a o e de da do das dos em no na nos nas um uma para por com que se ao aos the eu voce vc me te ele ela "
            "isso esse essa este esta foi sao ser era ter tem mais muito como qual quais quando onde ja nao sim "
            "senhor ghost ivan".split())
K1, B = 1.4, 0.75

_trava = threading.RLock()
_itens = None            # lista das trocas (em memória, só texto)
_termos = None           # Counter de palavras por troca, alinhado com _itens


def normalizar(texto):
    t = unicodedata.normalize("NFD", (texto or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return [p[:RAIZ] for p in re.findall(r"[a-z0-9]+", t) if p not in PARAR and len(p) > 1]


def _termos_de(item):
    return Counter(normalizar(f"{item['usuario']} {item['ghost']}"))


def _garantir_cache():
    global _itens, _termos
    with _trava:
        if _itens is None:
            _itens = [i for i in arquivo.ler_jsonl(ARQ_TEXTO) if i.get("usuario") and i.get("ghost")]
            _termos = [_termos_de(i) for i in _itens]
        return _itens, _termos


def adicionar(usuario, ghost, quando=None):
    """Guarda uma troca (rápido: só texto, sem modelo e sem thread)."""
    if not usuario or not ghost:
        return
    item = {"t": quando or time.time(), "usuario": str(usuario)[:1500], "ghost": str(ghost)[:1500]}
    arquivo.acrescentar_jsonl(ARQ_TEXTO, item)
    with _trava:
        if _itens is not None:
            _itens.append(item)
            _termos.append(_termos_de(item))


def pontuar(consulta, termos_docs):
    """BM25: nota de cada documento para a consulta (função pura)."""
    q = set(normalizar(consulta))
    n = len(termos_docs)
    if not q or not n:
        return [0.0] * n
    media = sum(sum(t.values()) for t in termos_docs) / n or 1
    df = Counter(p for t in termos_docs for p in q if p in t)
    notas = []
    for t in termos_docs:
        tam, s = sum(t.values()), 0.0
        for p in q:
            f = t.get(p, 0)
            if f:
                idf = math.log(1 + (n - df[p] + 0.5) / (df[p] + 0.5))
                s += idf * f * (K1 + 1) / (f + K1 * (1 - B + B * tam / media))
        notas.append(s)
    return notas


def _data(s):
    return datetime.strptime(s[:10], "%Y-%m-%d").timestamp() if s else None


def buscar(pergunta, data_inicio="", data_fim="", quantidade=6):
    """Trocas que mais combinam com a pergunta (opcionalmente dentro de um período AAAA-MM-DD)."""
    itens, termos = _garantir_cache()
    with _trava:
        itens, termos = list(itens), list(termos)
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
        notas = pontuar(pergunta, [termos[i] for i in idx])
        ordem = [idx[k] for k in sorted(range(len(idx)), key=lambda k: -notas[k])[:quantidade] if notas[k] > 0]
    else:
        ordem = idx[-quantidade:]
    if not ordem:
        return "Não encontrei nada com essas palavras nas conversas guardadas."
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
    return n
