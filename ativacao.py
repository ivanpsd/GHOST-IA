"""
GHOST - Ativação por voz: diga "Ghost, ..." sem segurar o F9.

Como funciona (100% local até detectar o nome):
1. O microfone fica ouvindo com um reconhecedor OFFLINE (Vosk) que só sabe
   uma palavra: "ghost". Nada vai para a internet nessa etapa.
2. Quando uma frase termina e ela COMEÇA com "ghost", o áudio dessa frase
   vai para o Whisper (como no F9) e uma 2ª conferência confirma que a
   frase começa mesmo com "Ghost" (evita "Gosto...", "Costa...").
3. Se você disser só "Ghost", ele responde "Sim, senhor?" e a próxima frase
   (até ESPERA_COMANDO segundos) vale como comando, sem repetir o nome.
4. Se você disser "Ghost" enquanto ele fala, ele para de falar (interrupção).
Depois de uma pergunta do Ghost, a próxima frase também vale como resposta.
O F9 continua funcionando normalmente.
"""
import io
import json
import time
import wave
import queue
import threading

import sounddevice as sd
import vosk

import os
PASTA_GHOST = os.path.dirname(os.path.abspath(__file__))
MODELO = os.path.join(PASTA_GHOST, "modelos", "vosk-model-small-en-us-0.15")

ATIVAR_AO_INICIAR = True
TAXA = 16000
ESPERA_COMANDO = 8        # segundos para falar o comando depois de "Ghost" ou de uma pergunta dele
MAX_FRASE = 15            # segundos máximos de uma frase

_fila_audio = queue.Queue()
_pausado = threading.Event()
_ativo = False
_aguardando_ate = 0.0
_rec = None
_buffer = bytearray()
_entregar = _falando = _interromper = None


def _para_wav(pcm):
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(TAXA); w.writeframes(pcm)
    return b.getvalue()


def _callback(indata, frames, tempo, status):
    _fila_audio.put(bytes(indata))


def _resetar():
    global _buffer
    _buffer = bytearray()
    if _rec:
        _rec.Reset()
    while not _fila_audio.empty():
        try:
            _fila_audio.get_nowait()
        except queue.Empty:
            break


def aguardar_comando(segundos=ESPERA_COMANDO):
    """A próxima frase vale como comando, sem precisar dizer 'Ghost'."""
    global _aguardando_ate
    _resetar()  # descarta o que foi ouvido enquanto o próprio Ghost falava
    _aguardando_ate = time.time() + segundos
    try:
        import hud; hud.ouvindo(f"Pode responder… ({int(segundos)} s)")
    except Exception:
        pass


def pausar():
    _pausado.set()


def retomar():
    _resetar()
    _pausado.clear()


def _loop():
    global _rec, _buffer, _aguardando_ate
    vosk.SetLogLevel(-1)
    modelo = vosk.Model(MODELO)
    _rec = vosk.KaldiRecognizer(modelo, TAXA, json.dumps(["ghost", "[unk]"]))
    with sd.RawInputStream(samplerate=TAXA, blocksize=4000, dtype="int16", channels=1, callback=_callback):
        print("\n[ATIVAÇÃO]: ouvindo a palavra \"Ghost\" (offline).")
        while _ativo:
            try:
                dados = _fila_audio.get(timeout=1)
            except queue.Empty:
                continue
            if _pausado.is_set():
                continue
            _buffer.extend(dados)
            if len(_buffer) > MAX_FRASE * TAXA * 2:
                del _buffer[: len(_buffer) - MAX_FRASE * TAXA * 2]

            if _rec.AcceptWaveform(dados):  # fim de uma frase (pausa na fala)
                palavras = json.loads(_rec.Result()).get("text", "").split()
                frase = bytes(_buffer)
                _buffer = bytearray()
                if not palavras:
                    continue
                if time.time() < _aguardando_ate:          # resposta/comando sem precisar do nome
                    _aguardando_ate = 0.0
                    _entregar({"wav": _para_wav(frase), "verificar_nome": False, "so_nome": False})
                elif palavras[0] == "ghost":
                    try:
                        import hud; hud.pensando("Ouvi \"Ghost\"…")
                    except Exception:
                        pass
                    so_nome = len(palavras) == 1 and len(frase) < 2.5 * TAXA * 2
                    _entregar({"wav": _para_wav(frase), "verificar_nome": True, "so_nome": so_nome})
            else:
                parcial = json.loads(_rec.PartialResult()).get("partial", "").split()
                if parcial[:1] == ["ghost"] and _falando and _falando():
                    _interromper()  # "Ghost..." enquanto ele fala: para na hora


def _comecar():
    global _ativo
    if not os.path.isdir(MODELO):
        print("\n[ATIVAÇÃO]: modelo de voz offline não encontrado; use o F9.")
        return False
    if not _ativo:
        _ativo = True
        threading.Thread(target=_loop, daemon=True).start()
    return True


def iniciar(entregar, falando, interromper):
    """entregar(item): coloca o comando na fila do Ghost.
    falando(): True se o Ghost está falando. interromper(): para a fala."""
    global _entregar, _falando, _interromper
    _entregar, _falando, _interromper = entregar, falando, interromper
    if ATIVAR_AO_INICIAR:
        _comecar()


def ligar(on, falar=None):
    global _ativo
    if on:
        ok = _comecar()
        if falar:
            falar("Ativação por voz ligada, senhor." if ok else "Senhor, o modelo de voz offline não está instalado.")
    else:
        _ativo = False
        if falar:
            falar("Ativação por voz desligada. Use o F9, senhor.")
