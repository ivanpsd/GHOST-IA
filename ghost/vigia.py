"""
GHOST - Vigia: inicia o Ghost e o reinicia sozinho se ele cair.

    pythonw -m ghost.vigia      (é o que fica na inicialização do Windows: atalho GHOST.lnk)

- Saída normal (código 0, ex.: "Ghost já está em execução") -> o vigia também encerra.
- Código 3 (falta configurar o .env) -> não reinicia: o próprio Ghost já mostrou o aviso.
- Queda (qualquer outro código) -> anota em logs/ghost.log e reinicia em 5 segundos.
- 5 quedas em 10 minutos -> para de insistir e mostra um aviso na tela
  (algo está errado de verdade; veja logs/travamentos.log).
"""
import ctypes
import os
import subprocess
import sys
import time
from datetime import datetime

from ghost.nucleo import caminhos

MAX_QUEDAS, JANELA_S, ESPERA_S = 5, 600, 5
SAIDAS_FINAIS = {0: "encerrado normalmente", 3: "falta configurar o .env"}
CODIGOS = {0xC0000005: "acesso inválido à memória (biblioteca nativa)",
           0xC0000409: "estouro de pilha/buffer", 0xC000041D: "erro dentro de callback do Windows",
           0xC00000FD: "estouro de pilha", 0xC000013A: "fechado pelo Windows (Ctrl+C/desligamento)",
           1: "erro do Python (veja logs/ghost.log)"}
_mutex = None


def _anotar(texto):
    try:
        os.makedirs(caminhos.LOGS, exist_ok=True)
        with open(caminhos.log("ghost.log"), "a", encoding="utf-8") as f:
            f.write(f"\n[VIGIA {datetime.now():%d/%m/%Y %H:%M:%S}]: {texto}\n")
    except OSError:
        pass


def _aviso(texto):
    if os.name == "nt":
        ctypes.windll.user32.MessageBoxW(None, texto, "GHOST - Vigia", 0x30)


def _ja_rodando():
    global _mutex
    if os.name != "nt":
        return False
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _mutex = k32.CreateMutexW(None, False, "Local\\GHOST_VIGIA")
    return ctypes.get_last_error() == 183           # ERROR_ALREADY_EXISTS


def main():
    if _ja_rodando():
        return
    executavel = sys.executable                     # o mesmo Python (pythonw) que abriu o vigia
    quedas = []
    while True:
        inicio = time.time()
        try:
            codigo = subprocess.call([executavel, "-m", "ghost"], cwd=caminhos.RAIZ)
        except OSError as e:                         # Python sumiu (venv apagada?)
            _anotar(f"não consegui abrir o Ghost: {e}")
            _aviso(f"Não consegui abrir o GHOST:\n{e}\n\nRode instalar.bat de novo.")
            return
        if codigo in SAIDAS_FINAIS:
            if codigo:
                _anotar(f"o Ghost saiu: {SAIDAS_FINAIS[codigo]}. O vigia não vai reiniciar.")
            return
        codigo_u = codigo & 0xFFFFFFFF
        motivo = CODIGOS.get(codigo_u, "desconhecido")
        _anotar(f"o Ghost caiu (código {codigo_u:#010x}: {motivo}) após {time.time() - inicio:.0f}s. "
                f"Reiniciando em {ESPERA_S}s. Detalhes técnicos em logs/travamentos.log.")
        quedas = [t for t in quedas if time.time() - t < JANELA_S] + [time.time()]
        if len(quedas) >= MAX_QUEDAS:
            _anotar(f"{MAX_QUEDAS} quedas em {JANELA_S // 60} minutos: o vigia parou de reiniciar.")
            _aviso(f"O GHOST caiu {MAX_QUEDAS} vezes em {JANELA_S // 60} minutos e não será reiniciado.\n"
                   f"Veja {caminhos.log('travamentos.log')} e {caminhos.log('ghost.log')}.")
            return
        time.sleep(ESPERA_S)


if __name__ == "__main__":
    main()
