"""
GHOST - Gravação e leitura seguras de arquivos.

Gravar: escreve num .tmp e troca pelo definitivo de uma vez (os.replace). Se o PC ou o Ghost
cair no meio, o arquivo antigo continua inteiro (nunca fica vazio ou pela metade).
No Windows, os.replace falha (WinError 5) se outro programa estiver lendo o arquivo naquele
instante (antivírus, OneDrive, outra thread): por isso tenta de novo algumas vezes.

Ler: ler_json() diferencia "não existe" (devolve o padrão) de "existe mas está corrompido"
(guarda uma cópia .corrompido e devolve o padrão), para nunca sobrescrever dados bons por engano.
"""
import json
import os
import shutil
import threading
import time

_trava = threading.Lock()
TENTATIVAS = 20
PAUSA = 0.05


def salvar_texto(caminho, texto, encoding="utf-8"):
    os.makedirs(os.path.dirname(os.path.abspath(caminho)), exist_ok=True)
    tmp = f"{caminho}.{threading.get_ident()}.tmp"
    with _trava:
        try:
            with open(tmp, "w", encoding=encoding) as f:
                f.write(texto)
                f.flush()
                os.fsync(f.fileno())
            for i in range(TENTATIVAS):
                try:
                    os.replace(tmp, caminho)
                    return
                except PermissionError:
                    if i == TENTATIVAS - 1:
                        raise
                    time.sleep(PAUSA)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass


def salvar_json(caminho, dados, indent=1):
    salvar_texto(caminho, json.dumps(dados, ensure_ascii=False, indent=indent))


class ArquivoCorrompido(Exception):
    """O arquivo existe mas não pôde ser lido: quem chamou NÃO deve gravar por cima."""


def ler_json(caminho, padrao=None, tolerar_corrompido=False):
    """Lê JSON. Sem arquivo: devolve `padrao`. Corrompido: copia para .corrompido e
    levanta ArquivoCorrompido (ou devolve o padrão se tolerar_corrompido=True)."""
    for _ in range(TENTATIVAS):
        try:
            with open(caminho, "r", encoding="utf-8-sig") as f:
                return json.load(f)
        except FileNotFoundError:
            return padrao
        except PermissionError:
            time.sleep(PAUSA)
        except (ValueError, UnicodeDecodeError) as e:
            try:
                shutil.copy2(caminho, caminho + ".corrompido")
            except OSError:
                pass
            print(f"\n[ARQUIVO]: {os.path.basename(caminho)} está corrompido ({e}); cópia guardada em .corrompido.")
            if tolerar_corrompido:
                return padrao
            raise ArquivoCorrompido(caminho) from e
    raise PermissionError(f"não consegui ler {caminho}")


def ler_jsonl(caminho):
    """Lê um arquivo de uma linha JSON por linha, pulando linhas quebradas (queda de energia no meio)."""
    itens = []
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            for linha in f:
                linha = linha.strip()
                if linha:
                    try:
                        itens.append(json.loads(linha))
                    except ValueError:
                        continue
    except FileNotFoundError:
        pass
    return itens


def acrescentar_jsonl(caminho, item):
    os.makedirs(os.path.dirname(os.path.abspath(caminho)), exist_ok=True)
    with _trava:
        with open(caminho, "a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
