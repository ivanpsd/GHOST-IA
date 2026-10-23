"""
GHOST - Baixa os modelos locais (uma vez só, ~4 GB no total; só baixa o que faltar). Rode:
    .\\.venv\\Scripts\\python.exe -m ghost.instalar_modelos
- faster-whisper "small" (voz -> texto sem internet)        ~470 MB
- voz Piper pt-BR "faber" (texto -> voz sem internet)       ~60 MB
- openWakeWord (base do detector de "Ghost" + exemplos)    ~180 MB
- modelo de sentido multilíngue (memória de longo prazo)    ~220 MB
- Ollama gemma3:4b (IA sem internet; precisa do Ollama)    ~3,3 GB
"""
import os
import shutil
import subprocess
import sys
import urllib.request

from ghost.nucleo import caminhos

VOZ = "https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx"


def passo(nome, func):
    print(f"\n== {nome}", flush=True)
    try:
        func()
        print("   ok", flush=True)
        return True
    except Exception as e:
        print(f"   FALHOU: {e}", flush=True)
        return False


def whisper():
    from ghost.voz import offline
    offline._carregar_whisper()


def piper():
    os.makedirs(caminhos.modelo("piper"), exist_ok=True)
    for ext in ("", ".json"):
        destino = caminhos.modelo("piper", "pt_BR-faber-medium.onnx" + ext)
        if os.path.exists(destino) and os.path.getsize(destino) > 0:
            continue
        try:
            with urllib.request.urlopen(VOZ + ext, timeout=60) as r, open(destino + ".tmp", "wb") as f:
                shutil.copyfileobj(r, f, 1 << 20)
            os.replace(destino + ".tmp", destino)
        finally:
            if os.path.exists(destino + ".tmp"):
                os.remove(destino + ".tmp")


def palavra():
    from ghost.voz import palavra as p
    p._features_obj()
    p._negativos_gerais()


def sentido():
    from ghost.ia import memoria_longa
    memoria_longa._embed(["teste"])


def ollama():
    from ghost.voz import offline
    exe = shutil.which("ollama") or os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe")
    if not os.path.exists(exe):
        raise RuntimeError("Ollama não instalado (winget install Ollama.Ollama)")
    subprocess.run([exe, "pull", offline.MODELO_OLLAMA], check=True)


def main():
    os.chdir(caminhos.RAIZ)
    caminhos.migrar()
    resultados = [passo(nome, f) for nome, f in (
        ("Whisper local", whisper), ("Voz Piper", piper), ("Detector de palavra", palavra),
        ("Memória de sentido", sentido), ("IA local (Ollama)", ollama))]
    return 0 if all(resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
