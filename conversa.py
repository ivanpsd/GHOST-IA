"""
GHOST - Memória de curto prazo (contexto da conversa).

Guarda as últimas trocas para a IA entender "e ele?", "explica melhor",
"fecha isso" e não perguntar de novo o que já foi dito.
Fica salvo em conversa_recente.json (sobrevive ao reinício) e expira
depois de um tempo sem conversar, para assuntos antigos não confundirem.
"""
import os
import json
import time
import threading

PASTA_GHOST = os.path.dirname(os.path.abspath(__file__))
ARQUIVO = os.path.join(PASTA_GHOST, "conversa_recente.json")
MAX_TROCAS = 12            # últimas perguntas/respostas enviadas à IA
EXPIRA_MINUTOS = 45        # sem falar com o Ghost por mais que isso, o contexto recomeça

_trava = threading.Lock()


def _carregar():
    try:
        with open(ARQUIVO, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _salvar(trocas):
    tmp = ARQUIVO + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(trocas[-MAX_TROCAS:], f, ensure_ascii=False, indent=1)
    os.replace(tmp, ARQUIVO)


def recentes():
    """Trocas ainda válidas (a mais antiga primeiro)."""
    with _trava:
        trocas = _carregar()
    if trocas and time.time() - trocas[-1]["t"] > EXPIRA_MINUTOS * 60:
        return []
    return trocas[-MAX_TROCAS:]


def registrar(usuario, ghost):
    with _trava:
        trocas = _carregar()
        if trocas and time.time() - trocas[-1]["t"] > EXPIRA_MINUTOS * 60:
            trocas = []
        trocas.append({"t": time.time(), "usuario": usuario, "ghost": ghost})
        _salvar(trocas)
    try:
        import memoria_longa            # guarda também na memória de longo prazo (pesquisável)
        memoria_longa.adicionar(usuario, ghost)
    except Exception as e:
        print(f"\n[MEMÓRIA LONGA]: {e}")


def como_mensagens():
    """Formato de chat (Groq): pares user/assistant."""
    msgs = []
    for t in recentes():
        msgs.append({"role": "user", "content": t["usuario"]})
        msgs.append({"role": "assistant", "content": t["ghost"]})
    return msgs


def como_texto():
    """Formato de texto corrido (Gemini, reserva)."""
    trocas = recentes()
    if not trocas:
        return ""
    linhas = "\n".join(f"Usuário: {t['usuario']}\nGHOST: {t['ghost']}" for t in trocas)
    return f"CONVERSA RECENTE (contexto):\n{linhas}\n\n"


def limpar():
    with _trava:
        _salvar([])
