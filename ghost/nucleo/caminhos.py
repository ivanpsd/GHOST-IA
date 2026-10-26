"""
GHOST - Onde fica cada coisa no disco (um só lugar para todos os módulos).

    <raiz>/            programa, .env, scripts de dois cliques
    <raiz>/dados/      tudo o que é SEU: memória, fichas, skills, lembretes, histórico,
                       gestos, treino da palavra "Ghost" (fora do Git)
    <raiz>/logs/       ghost.log e travamentos.log (fora do Git)
    <raiz>/modelos/    modelos baixados (voz, Whisper, Vosk, MediaPipe...) (fora do Git)
    <raiz>/prints/     capturas de tela pedidas por voz (fora do Git)

migrar() move os arquivos pessoais da versão antiga (que ficavam soltos na raiz)
para dados/ e logs/ — roda sozinho no início, uma vez, sem apagar nada.
"""
import os
import shutil

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DADOS = os.path.join(RAIZ, "dados")
LOGS = os.path.join(RAIZ, "logs")
MODELOS = os.path.join(RAIZ, "modelos")
PRINTS = os.path.join(RAIZ, "prints")
ENV = os.path.join(RAIZ, ".env")

# arquivos pessoais que a versão antiga guardava na raiz
_ANTIGOS_DADOS = ("apps_cache.json", "casa_dispositivos.json", "conversa_recente.json", "gestos_cadastro.json",
                  "lembretes.json", "memoria_aprendizado.json", "memoria_ghost.json", "pessoas.json",
                  "preferencias.json", "skills.json", "humor_log.jsonl", "rotina_log.jsonl",
                  "historico_completo.jsonl", "historico_vetores.npy", "credentials.json", "token_google.json")
_ANTIGOS_LOGS = ("ghost.log", "ghost.log.1", "travamentos.log", "travamentos.log.1")
# treino da palavra "Ghost" (é a SUA voz: vai para dados/, não para modelos/)
_ANTIGOS_PALAVRA = ("positivos.npy", "negativos.npy", "classificador.joblib", "classificador_antigo.joblib")


def dado(nome):
    return os.path.join(DADOS, nome)


def log(nome):
    return os.path.join(LOGS, nome)


def modelo(*partes):
    return os.path.join(MODELOS, *partes)


def _mover(origem, destino):
    if not os.path.exists(origem):
        return False
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    if os.path.exists(destino):
        # os dois existem: não sobrescreve nada; o antigo vai para dados/ com outro nome (o senhor decide depois)
        antigo = destino + ".antigo"
        if os.path.exists(antigo):
            return False
        shutil.move(origem, antigo)
        print(f"[SISTEMA]: {os.path.basename(origem)} existia na raiz e em dados/; o da raiz ficou como {antigo}.")
        return True
    shutil.move(origem, destino)
    return True


def migrar():
    """Cria as pastas e traz os arquivos da versão antiga. Devolve quantos arquivos foram movidos."""
    for p in (DADOS, LOGS, MODELOS, PRINTS):
        os.makedirs(p, exist_ok=True)
    movidos = 0
    for nome in _ANTIGOS_DADOS:
        movidos += _mover(os.path.join(RAIZ, nome), dado(nome))
    for nome in _ANTIGOS_LOGS:
        movidos += _mover(os.path.join(RAIZ, nome), log(nome))
    for nome in _ANTIGOS_PALAVRA:
        movidos += _mover(modelo("palavra", nome), dado(os.path.join("palavra", nome)))
    return movidos
