"""
GHOST - Para onde vai o que o Ghost "fala" no pedido atual.

Normalmente: alto-falante. Num pedido vindo do Telegram: de volta para o celular, por escrito.
O destino vale para a thread que atende o pedido E para as threads que ela abrir
(ações locais e confirmações rodam em segundo plano) — por isso use canal.thread()
em vez de threading.Thread para trabalho disparado por um pedido.
"""
import threading

_local = threading.local()


def atual():
    """Função que recebe o texto (ex.: envia ao Telegram) ou None = falar em voz alta."""
    return getattr(_local, "destino", None)


def definir(destino):
    _local.destino = destino


def thread(alvo, *args, nome=None):
    """Inicia uma thread que herda o destino da fala de quem a criou."""
    herdado = atual()

    def rodar():
        definir(herdado)
        try:
            alvo(*args)
        except Exception as e:
            print(f"\n[GHOST]: erro em segundo plano ({getattr(alvo, '__name__', 'tarefa')}): {e!r}")

    t = threading.Thread(target=rodar, daemon=True, name=nome)
    t.start()
    return t
