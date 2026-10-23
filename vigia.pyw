"""
GHOST - Vigia: inicia o Ghost e o reinicia sozinho se ele cair.

- Saída normal (código 0, ex.: "Ghost já está em execução") -> o vigia também encerra.
- Queda (qualquer outro código) -> anota em ghost.log e reinicia em 5 segundos.
- 5 quedas em 10 minutos -> para de insistir e mostra um aviso na tela
  (algo está errado de verdade; veja travamentos.log).
É este arquivo que fica na inicialização do Windows (atalho GHOST.lnk).
"""
import os
import sys
import time
import ctypes
import subprocess
from datetime import datetime

PASTA = os.path.dirname(os.path.abspath(__file__))
MAX_QUEDAS, JANELA_S, ESPERA_S = 5, 600, 5
CODIGOS = {0xC0000005: "acesso inválido à memória (biblioteca nativa)",
           0xC0000409: "estouro de pilha/buffer", 0xC000041D: "erro dentro de callback do Windows",
           0xC00000FD: "estouro de pilha", 1: "erro do Python (veja ghost.log)"}

_mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\GHOST_VIGIA")
if ctypes.windll.kernel32.GetLastError() == 183:      # já há um vigia rodando
    sys.exit(0)


def _anotar(texto):
    with open(os.path.join(PASTA, "ghost.log"), "a", encoding="utf-8") as f:
        f.write(f"\n[VIGIA {datetime.now():%d/%m/%Y %H:%M:%S}]: {texto}\n")


def main():
    executavel = sys.executable                       # o mesmo Python (pythonw) que abriu o vigia
    quedas = []
    while True:
        inicio = time.time()
        codigo = subprocess.call([executavel, os.path.join(PASTA, "ghost.py")], cwd=PASTA)
        if codigo == 0:
            return
        codigo_u = codigo & 0xFFFFFFFF
        motivo = CODIGOS.get(codigo_u, "desconhecido")
        _anotar(f"o Ghost caiu (código {codigo_u:#010x}: {motivo}) após {time.time() - inicio:.0f}s. "
                f"Reiniciando em {ESPERA_S}s. Detalhes técnicos em travamentos.log.")
        quedas = [t for t in quedas if time.time() - t < JANELA_S] + [time.time()]
        if len(quedas) >= MAX_QUEDAS:
            _anotar(f"{MAX_QUEDAS} quedas em {JANELA_S // 60} minutos: o vigia parou de reiniciar.")
            ctypes.windll.user32.MessageBoxW(
                None, f"O GHOST caiu {MAX_QUEDAS} vezes em {JANELA_S // 60} minutos e não será reiniciado.\n"
                      f"Veja C:\\GHOST\\travamentos.log e C:\\GHOST\\ghost.log.", "GHOST - Vigia", 0x30)
            return
        time.sleep(ESPERA_S)


if __name__ == "__main__":
    main()
