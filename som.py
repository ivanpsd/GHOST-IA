"""
GHOST - Acesso ÚNICO ao áudio (alto-falante e microfone).

A biblioteca de áudio (PortAudio) NÃO aguenta duas threads abrindo/fechando
streams ao mesmo tempo: isso derrubava o Ghost sem mensagem nenhuma
(erro 0xc0000005 no ntdll.dll). Aqui:
- abrir/fechar qualquer stream passa por uma trava (PA);
- só uma fala toca por vez, num alto-falante que fica aberto (nada de sd.play/sd.stop globais);
- parar() só levanta uma bandeira; quem fecha o stream é a própria thread que toca.
"""
import threading
from contextlib import contextmanager

import numpy as np
import sounddevice as sd

import eco

PA = threading.RLock()            # abrir/fechar streams: nunca em paralelo
_saida = threading.Lock()         # uma fala por vez
_parar = threading.Event()
BLOCO_S = 0.05                    # parar() responde em até 50 ms


_stream = None                    # alto-falante fica ABERTO (abrir/fechar a cada frase atrapalhava o microfone)


def _saida_para(fs, canais):
    global _stream
    if _stream is not None and (_stream.samplerate != fs or _stream.channels != canais or not _stream.active):
        with PA:
            try:
                _stream.close()
            except Exception:
                pass
        _stream = None
    if _stream is None:
        with PA:
            _stream = sd.OutputStream(samplerate=fs, channels=canais, dtype="float32", latency="low")
            _stream.start()
    return _stream


def tocar(data, fs):
    """Toca e só retorna quando terminar (ou quando parar() for chamado)."""
    global _stream
    data = np.asarray(data, dtype=np.float32)
    if data.ndim == 1:
        data = data.reshape(-1, 1)
    with _saida:
        _parar.clear()
        try:
            stream = _saida_para(fs, data.shape[1])
            passo = max(1, int(fs * BLOCO_S))
            for i in range(0, len(data), passo):
                if _parar.is_set():
                    break
                bloco = np.ascontiguousarray(data[i:i + passo])
                eco.alimentar_saida(bloco, fs)      # o cancelamento de eco precisa saber o que está tocando
                stream.write(bloco)
        except Exception:
            with PA:                      # stream com problema: descarta e abre outro na próxima fala
                try:
                    _stream.close()
                except Exception:
                    pass
            _stream = None
            raise


def parar():
    _parar.set()


@contextmanager
def entrada(**kw):
    """Microfone aberto/fechado sob a mesma trava."""
    with PA:
        stream = sd.RawInputStream(**kw)
        stream.start()
    try:
        yield stream
    finally:
        with PA:
            try:
                stream.stop()
            finally:
                stream.close()
