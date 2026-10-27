"""
GHOST - Ativação: SÓ PELO F9 (segure, fale, solte).

A ativação pela palavra "Ghost" (microfone sempre aberto, detector treinado, Vosk, cancelamento de eco) foi
retirada em 27/10/2026 para economizar memória e CPU (~130 MB e o microfone ligado o tempo todo) e acabar com
os acionamentos falsos. O microfone abre só enquanto o F9 está apertado.

Modos: "normal" e "dormindo" ("tchau Ghost" = não perturbe: avisos esperam até o próximo F9).
As funções abaixo mantêm os nomes antigos para o resto do Ghost não precisar mudar.
"""
import time

from ghost.voz import som

TAXA = 16000
_modo = "normal"


def definir_modo(novo):
    global _modo
    _modo = "dormindo" if novo == "dormindo" else "normal"
    print(f"\n[ATIVAÇÃO]: modo {_modo}.")


def modo():
    return _modo


def gravar_enquanto(condicao, maximo=60):
    """Grava do microfone enquanto condicao() for verdadeira (F9 apertado). Devolve PCM 16 kHz mono."""
    blocos = []
    with som.entrada(samplerate=TAXA, blocksize=1600, dtype="int16", channels=1,
                     callback=lambda d, f, t, s: blocos.append(bytes(d))):
        inicio = time.time()
        while condicao() and time.time() - inicio < maximo:
            time.sleep(0.03)
        time.sleep(0.15)                  # pega o último bloco que ainda estava chegando
    return b"".join(blocos)


def aguardar_comando(segundos=0):
    """Depois de uma pergunta do Ghost: mostra na faixa que é para responder com o F9."""
    try:
        from ghost.nucleo import hud
        hud.ouvindo("Responda segurando o F9")
    except Exception:
        pass


# Sem microfone aberto não há "janela de resposta" nem medição de silêncio na sala.
def janela_aberta():
    return False


def segundos_sem_voz():
    return float("inf")


def definir_interrompivel(_funcao):
    pass


def iniciar(*_args):
    print("\n[ATIVAÇÃO]: só pelo F9 (segure, fale, solte).")
