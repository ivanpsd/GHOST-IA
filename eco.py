"""
GHOST - Cancelamento de eco (WebRTC, o mesmo das chamadas de vídeo), gratuito e local.

Sem isso, enquanto o Ghost fala o microfone ouve a própria voz dele e não dá para
você falar por cima. Com o cancelamento:
- tudo o que vai para o alto-falante é registrado aqui (alimentar_saida);
- o áudio do microfone passa por limpar_entrada, que subtrai a voz do Ghost
  e reduz ruído de fundo. O que sobra é praticamente só a SUA voz.
Se a biblioteca (livekit) não estiver instalada, tudo continua funcionando, só sem
cancelamento (não dá para interromper falando por cima, só dizendo "Ghost").
"""
import threading

import numpy as np

TAXA = 16000
QUADRO = TAXA // 100            # o WebRTC trabalha com quadros de 10 ms (160 amostras)
ATRASO_MS = 120                 # atraso aproximado alto-falante -> microfone (o WebRTC refina sozinho)

_apm = None
_trava = threading.Lock()
_resto_saida = np.zeros(0, dtype=np.int16)
_resto_entrada = b""
ativo = False


def iniciar():
    """Liga o cancelamento de eco. Devolve True se funcionou."""
    global _apm, ativo
    try:
        from livekit import rtc
        _apm = rtc.AudioProcessingModule(echo_cancellation=True, noise_suppression=True,
                                         high_pass_filter=True, auto_gain_control=False)
        _apm.set_stream_delay_ms(ATRASO_MS)
        ativo = True
        print("\n[ECO]: cancelamento de eco ligado (pode falar por cima do Ghost).")
    except Exception as e:
        ativo = False
        print(f"\n[ECO]: cancelamento de eco indisponível ({e}). Interrompa dizendo \"Ghost\".")
    return ativo


def _quadro(pcm16):
    from livekit import rtc
    return rtc.AudioFrame(bytearray(pcm16.tobytes()), TAXA, 1, QUADRO)


def alimentar_saida(data, fs):
    """Recebe o que está indo para o alto-falante (float32, qualquer taxa, mono/estéreo)."""
    global _resto_saida
    if not ativo:
        return
    try:
        a = np.asarray(data, dtype=np.float32)
        if a.ndim > 1:
            a = a.mean(axis=1)
        if fs != TAXA:
            n = int(len(a) * TAXA / fs)
            a = np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a) if n else a[:0]
        pcm = np.clip(a * 32767, -32768, 32767).astype(np.int16)
        with _trava:
            pcm = np.concatenate([_resto_saida, pcm])
            n = len(pcm) // QUADRO * QUADRO
            for i in range(0, n, QUADRO):
                _apm.process_reverse_stream(_quadro(pcm[i:i + QUADRO]))
            _resto_saida = pcm[n:]
    except Exception as e:
        print(f"\n[ECO]: erro na saída ({e}).")


def limpar_entrada(dados):
    """Recebe bytes int16 mono 16 kHz do microfone e devolve os mesmos bytes sem o eco do Ghost."""
    global _resto_entrada
    if not ativo:
        return dados
    try:
        bruto = _resto_entrada + dados
        n = len(bruto) // (QUADRO * 2) * (QUADRO * 2)
        saida = bytearray()
        with _trava:
            for i in range(0, n, QUADRO * 2):
                q = _quadro(np.frombuffer(bruto[i:i + QUADRO * 2], dtype=np.int16))
                _apm.set_stream_delay_ms(ATRASO_MS)
                _apm.process_stream(q)
                saida.extend(bytes(q.data.cast("B")))
        _resto_entrada = bruto[n:]
        return bytes(saida)
    except Exception as e:
        print(f"\n[ECO]: erro na entrada ({e}); seguindo sem cancelamento.")
        return dados
