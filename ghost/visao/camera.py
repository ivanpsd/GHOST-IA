"""
GHOST - Câmera compartilhada.

Uma única captura serve aos gestos e à leitura facial ao mesmo tempo
(o Windows não deixa dois programas abrirem a mesma webcam).
A câmera só fica ligada enquanto algum módulo estiver usando.
A imagem nunca é gravada em disco.
"""
import threading
import time

import cv2

INDICE_CAMERA = 0
LARGURA, ALTURA = 640, 480

_trava = threading.Condition()
_consumidores = set()
_suspensos = set()
_n_suspensoes = 0          # suspender_todos() pode ser chamado mais de uma vez (cadastro aberto 2x)
_thread = None
_frame = None
_frame_id = 0
erro = None


def _criar_thread():
    """Chamar com _trava. Cria a thread da câmera se não houver uma rodando."""
    global _thread, erro
    if _thread is None and _consumidores and not _n_suspensoes:
        erro = None
        _thread = threading.Thread(target=_loop, daemon=True, name="camera")
        _thread.start()


def _loop():
    global _frame, _frame_id, _thread, erro
    cap = cv2.VideoCapture(INDICE_CAMERA, cv2.CAP_DSHOW)
    try:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, LARGURA)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, ALTURA)
        if not cap.isOpened():
            erro = "não consegui acessar a câmera (pode estar em uso por outro programa)"
            return
        erro = None
        falhas = 0
        while True:
            with _trava:
                if not _consumidores:
                    break
            ok, f = cap.read()
            if not ok:
                falhas += 1
                if falhas > 30:
                    erro = "a câmera parou de enviar imagens"
                    break
                time.sleep(0.05)
                continue
            falhas = 0
            f = cv2.flip(f, 1)  # espelho: sua direita é a direita da imagem
            with _trava:
                _frame, _frame_id = f, _frame_id + 1
                _trava.notify_all()
    finally:
        cap.release()                       # no DirectShow pode levar centenas de ms
        with _trava:
            _frame = None
            _thread = None
            # alguém pediu a câmera enquanto esta thread fechava: abre de novo (antes ficava sem câmera)
            if _consumidores and erro is None:
                _criar_thread()
            _trava.notify_all()


def iniciar(nome):
    """Registra um módulo como usuário da câmera (liga se estiver desligada).
    Com a câmera suspensa (cadastro de gestos aberto), só anota e liga quando ela for retomada."""
    with _trava:
        if _n_suspensoes:
            _suspensos.add(nome)
            return
        _consumidores.add(nome)
        _criar_thread()


def parar(nome):
    """Remove o módulo; sem ninguém usando, a câmera desliga."""
    with _trava:
        _consumidores.discard(nome)
        _suspensos.discard(nome)            # desligado durante a suspensão: não volta sozinho depois


def ler(ultimo_id=0, timeout=1.0):
    """Espera um quadro mais novo que ultimo_id. Retorna (id, quadro) ou (ultimo_id, None)."""
    fim = time.monotonic() + timeout
    with _trava:
        while _frame_id <= ultimo_id or _frame is None:
            resta = fim - time.monotonic()
            if resta <= 0 or (_thread is None and erro):
                return ultimo_id, None
            _trava.wait(resta)
        return _frame_id, _frame


def em_uso():
    with _trava:
        return set(_consumidores)


def suspensa():
    with _trava:
        return _n_suspensoes > 0


def suspender_todos():
    """Libera a câmera para outro programa (ex.: tela de cadastro de gestos)."""
    global _n_suspensoes
    with _trava:
        _n_suspensoes += 1
        _suspensos.update(_consumidores)
        _consumidores.clear()
    for _ in range(40):  # espera até 2 s a câmera ser liberada
        with _trava:
            if _thread is None:
                break
        time.sleep(0.05)
    with _trava:
        return set(_suspensos)


def retomar_todos():
    global _n_suspensoes
    with _trava:
        _n_suspensoes = max(0, _n_suspensoes - 1)
        if _n_suspensoes:
            return
        _consumidores.update(_suspensos)
        _suspensos.clear()
        _criar_thread()
