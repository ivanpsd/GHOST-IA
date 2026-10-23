"""
GHOST - Acesso ÚNICO ao áudio (alto-falante e microfone).

A biblioteca de áudio (PortAudio) NÃO aguenta duas threads abrindo/fechando
streams ao mesmo tempo: isso derrubava o Ghost sem mensagem nenhuma
(erro 0xc0000005 no ntdll.dll). Aqui:
- abrir/fechar qualquer stream passa por uma trava (PA);
- só uma fala toca por vez, num alto-falante que fica aberto (nada de sd.play/sd.stop globais);
- parar() só levanta uma bandeira; quem fecha o stream é a própria thread que toca;
- cada parar() abre uma nova "geração": áudios gerados antes dela são descartados mesmo que
  ainda estejam na fila (assim interromper corta a resposta inteira, não só a frase atual).
"""
import threading
from contextlib import contextmanager

import numpy as np
import sounddevice as sd

from ghost.voz import eco

PA = threading.RLock()            # abrir/fechar streams: nunca em paralelo
_saida = threading.Lock()         # uma fala por vez
_parar = threading.Event()
BLOCO_S = 0.05                    # parar() responde em até 50 ms
_geracao = 0


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


def geracao():
    """Marque cada áudio com isto ao criá-lo; tocar() descarta os de gerações antigas."""
    return _geracao


def tocar(data, fs, gen=None):
    """Toca e só retorna quando terminar (ou quando parar() for chamado).
    gen: geração em que o áudio foi pedido; se houve um parar() depois, não toca."""
    global _stream
    if gen is not None and gen != _geracao:
        return
    data = np.asarray(data, dtype=np.float32)
    if data.ndim == 1:
        data = data.reshape(-1, 1)
    with _saida:
        if gen is not None and gen != _geracao:
            return
        _parar.clear()
        minha = _geracao
        try:
            stream = _saida_para(fs, data.shape[1])
            ref = eco.reamostrar(data, fs)             # referência para o cancelamento de eco, 16 kHz
            passo = max(1, int(fs * BLOCO_S))
            for i in range(0, len(data), passo):
                if _parar.is_set() or minha != _geracao:
                    break
                bloco = np.ascontiguousarray(data[i:i + passo])
                if ref is not None:                    # índices proporcionais: sem desvio acumulado
                    eco.alimentar_ref(ref[i * eco.TAXA // fs:(i + passo) * eco.TAXA // fs])
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
    global _geracao
    _geracao += 1
    _parar.set()


def reiniciar_dispositivos():
    """Microfone/fone trocado ou Windows voltou da suspensão: fecha tudo e relê os dispositivos."""
    global _stream
    with PA:
        try:
            if _stream is not None:
                _stream.close()
        except Exception:
            pass
        _stream = None
        try:
            sd._terminate()
            sd._initialize()
        except Exception as e:
            print(f"\n[SOM]: não consegui reiniciar o áudio ({e}).")


@contextmanager
def entrada(**kw):
    """Microfone aberto/fechado sob a mesma trava."""
    with PA:
        stream = sd.RawInputStream(**kw)
        try:
            stream.start()
        except Exception:
            stream.close()               # não vaza o handle do PortAudio
            raise
    try:
        yield stream
    finally:
        with PA:
            try:
                stream.stop()
            finally:
                stream.close()
