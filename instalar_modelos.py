"""
GHOST - Baixa os modelos locais (uma vez só, ~4 GB no total). Rode:
    .\\.venv\\Scripts\\python.exe instalar_modelos.py
- faster-whisper "small" (voz -> texto sem internet)        ~470 MB
- voz Piper pt-BR "faber" (texto -> voz sem internet)       ~60 MB
- openWakeWord (base do detector de "Ghost" + exemplos)    ~180 MB
- modelo de sentido multilíngue (memória de longo prazo)    ~220 MB
- Ollama gemma3:4b (IA sem internet; precisa do Ollama)    ~3,3 GB
"""
import os
import shutil
import subprocess
import urllib.request

PASTA = os.path.dirname(os.path.abspath(__file__))
M = os.path.join(PASTA, "modelos")
VOZ = "https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx"


def passo(nome, func):
    print(f"\n== {nome}")
    try:
        func()
        print("   ok")
    except Exception as e:
        print(f"   FALHOU: {e}")


def whisper():
    import offline
    offline._carregar_whisper()


def piper():
    os.makedirs(os.path.join(M, "piper"), exist_ok=True)
    for ext in ("", ".json"):
        destino = os.path.join(M, "piper", "pt_BR-faber-medium.onnx" + ext)
        if not os.path.exists(destino):
            urllib.request.urlretrieve(VOZ + ext, destino + ".tmp")
            os.replace(destino + ".tmp", destino)


def palavra():
    import palavra as p
    p._features_obj()
    p._negativos_gerais()


def sentido():
    import memoria_longa
    memoria_longa._embed(["teste"])


def ollama():
    exe = shutil.which("ollama") or os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe")
    if not os.path.exists(exe):
        raise RuntimeError("Ollama não instalado (winget install Ollama.Ollama)")
    subprocess.run([exe, "pull", "gemma3:4b"], check=True)


if __name__ == "__main__":
    os.chdir(PASTA)
    for nome, f in (("Whisper local", whisper), ("Voz Piper", piper), ("Detector de palavra", palavra),
                    ("Memória de sentido", sentido), ("IA local (Ollama)", ollama)):
        passo(nome, f)
