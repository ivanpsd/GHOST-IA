"""
GHOST - Memória de curto prazo (contexto da conversa).

Guarda as últimas trocas para a IA entender "e ele?", "explica melhor",
"fecha isso" e não perguntar de novo o que já foi dito.
Fica salvo em dados/conversa_recente.json (sobrevive ao reinício) e expira
depois de um tempo sem conversar, para assuntos antigos não confundirem.
Também marca as trocas em que a IA leu conteúdo de fora (e-mail, tela, planilha...):
enquanto esse texto estiver no histórico, ações no PC pedem confirmação por voz.
"""
import threading
import time

from ghost.nucleo import arquivo, caminhos

ARQUIVO = caminhos.dado("conversa_recente.json")
MAX_TROCAS = 12            # últimas perguntas/respostas enviadas à IA
EXPIRA_MINUTOS = 45        # sem falar com o Ghost por mais que isso, o contexto recomeça

_trava = threading.Lock()


def _carregar():
    return arquivo.ler_json(ARQUIVO, [], tolerar_corrompido=True) or []


def _salvar(trocas):
    arquivo.salvar_json(ARQUIVO, trocas[-MAX_TROCAS:])


def recentes():
    """Trocas ainda válidas (a mais antiga primeiro)."""
    with _trava:
        trocas = _carregar()
    if trocas and time.time() - trocas[-1]["t"] > EXPIRA_MINUTOS * 60:
        return []
    return trocas[-MAX_TROCAS:]


def registrar(usuario, ghost, externo=False):
    with _trava:
        trocas = _carregar()
        if trocas and time.time() - trocas[-1]["t"] > EXPIRA_MINUTOS * 60:
            trocas = []
        trocas.append({"t": time.time(), "usuario": usuario, "ghost": ghost, "externo": bool(externo)})
        _salvar(trocas)
    try:
        from ghost.ia import memoria_longa  # guarda também na memória de longo prazo (pesquisável)
        memoria_longa.adicionar(usuario, ghost)
    except Exception as e:
        print(f"\n[MEMÓRIA LONGA]: {e}")


def teve_externo_recente():
    """True se alguma troca ainda no histórico enviado à IA trouxe conteúdo de fora."""
    return any(t.get("externo") for t in recentes())


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
