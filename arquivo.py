"""
GHOST - Gravação segura de arquivos.
Grava num .tmp e troca pelo definitivo de uma vez (os.replace): se o PC ou o
Ghost cair no meio, o arquivo antigo continua inteiro (nunca fica vazio/pela metade).
"""
import os
import json
import threading

_trava = threading.Lock()


def salvar_texto(caminho, texto, encoding="utf-8"):
    tmp = f"{caminho}.{threading.get_ident()}.tmp"
    with _trava:
        with open(tmp, "w", encoding=encoding) as f:
            f.write(texto)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, caminho)


def salvar_json(caminho, dados, indent=1):
    salvar_texto(caminho, json.dumps(dados, ensure_ascii=False, indent=indent))
