"""
GHOST - Câmera compartilhada.

Uma única captura serve aos gestos e à leitura facial ao mesmo tempo
(o Windows não deixa dois programas abrirem a mesma webcam).
A câmera só fica ligada enquanto algum módulo estiver usando.
A imagem nunca é gravada em disco.
"""
import time
import threading
import cv2

INDICE_CAMERA = 0
LARGURA, ALTURA = 640, 480

_trava = threading.Condition()
_consumidores = set()
_suspensos = set()
_thread = None
_frame = None
_frame_id = 0
erro = None


def _loop():
    global _frame, _frame_id, _thread, erro
    cap = cv2.VideoCapture(INDICE_CAMERA, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, LARGURA)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, ALTURA)
    if not cap.isOpened():
        erro = "não consegui acessar a câmera (pode estar em uso por outro programa)"
        with _trava:
            _thread = None
            _trava.notify_all()
        return
    erro = None
    falhas = 0
    try:
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
        cap.release()
        with _trava:
            _frame = None
            _thread = None
            _trava.notify_all()


def iniciar(nome):
    """Registra um módulo como usuário da câmera (liga se estiver desligada)."""
    global _thread
    with _trava:
        _consumidores.add(nome)
        if _thread is None:
            _thread = threading.Thread(target=_loop, daemon=True)
            _thread.start()


def parar(nome):
    """Remove o módulo; sem ninguém usando, a câmera desliga."""
    with _trava:
        _consumidores.discard(nome)


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


def suspender_todos():
    """Libera a câmera para outro programa (ex.: tela de cadastro de gestos)."""
    global _suspensos
    with _trava:
        _suspensos = set(_consumidores)
        _consumidores.clear()
    for _ in range(40):  # espera até 2 s a câmera ser liberada
        with _trava:
            if _thread is None:
                break
        time.sleep(0.05)
    return set(_suspensos)


def retomar_todos():
    global _suspensos
    for nome in list(_suspensos):
        iniciar(nome)
    _suspensos = set()
