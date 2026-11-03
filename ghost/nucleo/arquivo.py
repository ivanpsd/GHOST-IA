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


# ------------------------------------------------------------- backup diário da pasta dados/
BACKUP_FORA = ("painel_janela", "palavra", "apps_cache.json")   # perfil do navegador, sobras e cache: não precisam
BACKUP_MANTER = 7


def backup_dados(origem, destino, manter=BACKUP_MANTER, agora=None):
    """Zip de dados/ (memória, inventário, câmeras, skills, comandos ensinados...) em destino/ghost_dados_AAAA-MM-DD.zip.
    Guarda os 'manter' mais novos. Devolve o caminho do zip."""
    import zipfile
    from datetime import datetime
    os.makedirs(destino, exist_ok=True)
    nome = os.path.join(destino, f"ghost_dados_{datetime.fromtimestamp(agora or time.time()):%Y-%m-%d}.zip")
    tmp = nome + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for raiz, pastas, arquivos in os.walk(origem):
            pastas[:] = [p for p in pastas if p not in BACKUP_FORA]
            for a in arquivos:
                if a in BACKUP_FORA or a.endswith((".tmp", ".corrompido")):
                    continue
                caminho = os.path.join(raiz, a)
                try:
                    z.write(caminho, os.path.relpath(caminho, origem))
                except OSError:                      # arquivo em uso/sumiu no meio: segue com o resto
                    pass
    os.replace(tmp, nome)
    antigos = sorted(f for f in os.listdir(destino) if f.startswith("ghost_dados_") and f.endswith(".zip"))
    for f in antigos[:-manter]:
        os.remove(os.path.join(destino, f))
    return nome
