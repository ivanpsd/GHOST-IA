"""
GHOST - Modo SEM INTERNET (tudo local, gratuito).

| Parte          | Na nuvem (normal)        | Sem internet (reserva)                      |
|----------------|--------------------------|---------------------------------------------|
| Voz -> texto   | Whisper no Groq          | faster-whisper "small" no próprio PC        |
| Inteligência   | Groq / Gemini            | Ollama com gemma3:4b (mais simples/lento)   |
| Texto -> voz   | edge-tts (Antonio)       | Piper, voz pt-BR "faber" (mais robótica)    |

Quando a internet volta, ele volta para a nuvem sozinho (checagem a cada 20 s).
Modelos ficam em modelos/ (fora do Git). A IA local fica carregada só 2 min
depois do último uso, para não ocupar memória à toa.
"""
import io
import os
import json
import time
import socket
import threading

import numpy as np

PASTA = os.path.dirname(os.path.abspath(__file__))
PASTA_MODELOS = os.path.join(PASTA, "modelos")
MODELO_WHISPER = "small"
VOZ_PIPER = os.path.join(PASTA_MODELOS, "piper", "pt_BR-faber-medium.onnx")
OLLAMA_URL = "http://127.0.0.1:11434"
MODELO_OLLAMA = "gemma3:4b"
CHECAR_A_CADA = 20

_estado = {"t": 0.0, "on": True}
_whisper = _piper = None
_trava = threading.Lock()


# ---------------- internet ----------------
def internet_ok(forcar=False):
    """True/False com cache de 20 s (não atrasa cada comando)."""
    if not forcar and time.time() - _estado["t"] < CHECAR_A_CADA:
        return _estado["on"]
    on = False
    for host in (("1.1.1.1", 53), ("8.8.8.8", 53)):
        try:
            socket.create_connection(host, timeout=1.5).close()
            on = True
            break
        except OSError:
            continue
    if on != _estado["on"]:
        print(f"\n[OFFLINE]: {'internet voltou: usando a nuvem.' if on else 'sem internet: usando os modelos locais.'}")
        if not on:
            preaquecer()
            preaquecer_voz()
    _estado.update(t=time.time(), on=on)
    return on


def marcar_sem_internet():
    """Uma chamada à nuvem falhou por rede: assume offline até a próxima checagem."""
    _estado.update(t=time.time(), on=False)


# ---------------- voz -> texto ----------------
def _carregar_whisper():
    global _whisper
    with _trava:
        if _whisper is None:
            from faster_whisper import WhisperModel
            _whisper = WhisperModel(MODELO_WHISPER, device="cpu", compute_type="int8",
                                    download_root=os.path.join(PASTA_MODELOS, "whisper"))
    return _whisper


def _para_16k(audio_bytes):
    """WAV/OGG (áudio do Telegram) -> float32 mono 16 kHz, sem depender do ffmpeg/av."""
    import soundfile as sf
    a, fs = sf.read(io.BytesIO(audio_bytes), dtype="float32")
    if a.ndim > 1:
        a = a.mean(axis=1)
    if fs != 16000:
        a = np.interp(np.arange(0, len(a), fs / 16000), np.arange(len(a)), a).astype(np.float32)
    return a


def transcrever(audio_bytes):
    modelo = _carregar_whisper()
    # sem initial_prompt: com ele o modelo pequeno tende a "pular" o Ghost do começo da frase
    partes, _ = modelo.transcribe(_para_16k(audio_bytes), language="pt", beam_size=1, vad_filter=True)
    return " ".join(p.text.strip() for p in partes).strip()


# ---------------- texto -> voz ----------------
def _carregar_piper():
    global _piper
    with _trava:
        if _piper is None:
            from piper import PiperVoice
            _piper = PiperVoice.load(VOZ_PIPER)
    return _piper


def sintetizar(texto):
    """Devolve (áudio float32, taxa) como o edge-tts + soundfile."""
    voz = _carregar_piper()
    blocos = [c.audio_float_array for c in voz.synthesize(texto)]
    taxa = voz.config.sample_rate
    return (np.concatenate(blocos) if blocos else np.zeros(1, np.float32)).astype(np.float32), taxa


def preaquecer_voz():
    threading.Thread(target=lambda: voz_disponivel() and _carregar_piper(), daemon=True).start()


def voz_disponivel():
    return os.path.exists(VOZ_PIPER)


# ---------------- inteligência local ----------------
def ollama_ok():
    import requests
    try:
        tags = requests.get(f"{OLLAMA_URL}/api/tags", timeout=1.5).json()
        return any(m.get("name", "").startswith(MODELO_OLLAMA) for m in tags.get("models", []))
    except Exception:
        return False


def conversar(mensagens, ao_receber_frase, separar_frases):
    """Streaming do Ollama; cada frase pronta vai para a voz. Sem ferramentas (modo reserva)."""
    import requests
    aviso = {"role": "system", "content": "Você está SEM INTERNET, rodando localmente. Responda curto, em português, "
                                          "sem markdown. Se precisar de internet ou de agir no PC, diga que agora não dá."}
    r = requests.post(f"{OLLAMA_URL}/api/chat", stream=True, timeout=(3, 120), json={
        "model": MODELO_OLLAMA, "messages": [aviso] + mensagens, "stream": True, "keep_alive": "2m",
        "options": {"temperature": 0.3, "num_predict": 300}})
    r.raise_for_status()
    completo, buffer, primeira = "", "", True
    for linha in r.iter_lines():
        if not linha:
            continue
        pedaco = json.loads(linha).get("message", {}).get("content", "")
        completo += pedaco
        buffer += pedaco
        frases, buffer = separar_frases(buffer, primeira=primeira)
        for f in frases:
            primeira = False
            ao_receber_frase(f)
    if buffer.strip():
        ao_receber_frase(buffer.strip())
    return completo.strip()


def preaquecer():
    """Carrega o Whisper local em segundo plano (só se já estiver baixado), para a 1ª queda ser rápida."""
    def _rodar():
        try:
            if os.path.isdir(os.path.join(PASTA_MODELOS, "whisper")):
                _carregar_whisper()
        except Exception as e:
            print(f"\n[OFFLINE]: transcrição local indisponível ({e}).")
    threading.Thread(target=_rodar, daemon=True).start()
