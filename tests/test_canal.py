import threading

from ghost.nucleo import canal


def test_destino_e_herdado_pelas_threads():
    recebido = []
    canal.definir(recebido.append)
    resultado = {}

    def tarefa():
        resultado["destino"] = canal.atual()

    canal.thread(tarefa).join(2)
    assert resultado["destino"] == recebido.append
    canal.definir(None)


def test_thread_comum_nao_herda():
    canal.definir(print)
    resultado = {}
    t = threading.Thread(target=lambda: resultado.setdefault("d", canal.atual()))
    t.start()
    t.join(2)
    assert resultado["d"] is None
    canal.definir(None)


def test_erro_na_thread_nao_propaga(capsys):
    def explode():
        raise ValueError("boom")
    canal.thread(explode).join(2)
    assert "boom" in capsys.readouterr().out
