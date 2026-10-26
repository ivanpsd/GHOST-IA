"""
GHOST - Baixa os modelos locais (uma vez só; só baixa o que faltar). Rode:
    .\\.venv\\Scripts\\python.exe -m ghost.instalar_modelos
- openWakeWord (base do detector de "Ghost" + exemplos)    ~180 MB
- modelo de sentido multilíngue (memória de longo prazo)    ~220 MB
"""
import os
import sys

from ghost.nucleo import caminhos


def passo(nome, func):
    print(f"\n== {nome}", flush=True)
    try:
        func()
        print("   ok", flush=True)
        return True
    except Exception as e:
        print(f"   FALHOU: {e}", flush=True)
        return False


def palavra():
    from ghost.voz import palavra as p
    p._features_obj()
    p._negativos_gerais()


def sentido():
    from ghost.ia import memoria_longa
    memoria_longa._embed(["teste"])


def main():
    os.chdir(caminhos.RAIZ)
    caminhos.migrar()
    resultados = [passo(nome, f) for nome, f in (("Detector de palavra", palavra), ("Memória de sentido", sentido))]
    return 0 if all(resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
