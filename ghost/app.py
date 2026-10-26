"""
GHOST - Assistente pessoal por voz para Windows.

Fluxo: microfone (ativacao) -> fila de comandos -> transcrição (Whisper) -> ações locais
(automacoes) ou IA (Groq -> Gemini -> Ollama, com ferramentas) -> voz (edge-tts / Piper).
Este módulo junta tudo e roda o laço principal. Ponto de entrada: main().
"""
import os
import sys

# Silencia os avisos internos do MediaPipe/TensorFlow (W0000, INFO...): precisa vir antes de importá-los
os.environ.setdefault("GLOG_minloglevel", "2")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

import asyncio
import ctypes
import faulthandler
import hashlib
import io
import queue
import re
import threading
import time
import wave
from datetime import date, datetime

from ghost.nucleo import caminhos


class _LogRotativo:
    """ghost.log com limite de tamanho: passou de 2 MB, vira ghost.log.1 (guarda só 1 anterior).
    Várias threads escrevem ao mesmo tempo: a trava evita perder linhas na rotação."""
    LIMITE = 2_000_000

    def __init__(self, caminho):
        self.caminho, self._n = caminho, 0
        self._trava = threading.Lock()
        self._f = open(caminho, "a", encoding="utf-8", buffering=1)

    def write(self, texto):
        with self._trava:
            try:
                self._f.write(texto)
                self._n += 1
                if self._n % 200 == 0 and self._f.tell() > self.LIMITE:
                    self._f.close()
                    os.replace(self.caminho, self.caminho + ".1")
                    self._f = open(self.caminho, "a", encoding="utf-8", buffering=1)
            except Exception:
                pass
        return len(texto)

    def flush(self):
        with self._trava:
            try:
                self._f.flush()
            except Exception:
                pass

    def isatty(self):
        return False


class SemInternet(Exception):
    """Transcrição/voz/IA dependem da internet (a versão 8.1 não tem mais o modo local)."""


AVISO_SEM_INTERNET = "Senhor, estou sem internet no momento."
SAIDA_CONFIGURACAO = 3     # código de saída "falta configurar" (o vigia não reinicia; mostra aviso)
_mutex = None
_arq_travamentos = None


def _preparar_processo():
    """Tudo o que precisa acontecer antes de ligar microfone, câmera e IA."""
    global _mutex, _arq_travamentos
    os.chdir(caminhos.RAIZ)                      # caminhos relativos certos ao iniciar com o Windows
    movidos = caminhos.migrar()                   # versão antiga: traz dados soltos para dados/ e logs/

    # Rodando oculto (pythonw) não existe terminal: tudo vai para logs/ghost.log
    if sys.stdout is None or sys.stderr is None:
        sys.stdout = sys.stderr = _LogRotativo(caminhos.log("ghost.log"))

    # Travamentos dentro de bibliotecas (som, câmera, Vosk) fecham o Python sem mensagem.
    # O faulthandler grava em logs/travamentos.log ONDE foi a queda, em todas as threads.
    trav = caminhos.log("travamentos.log")
    if os.path.exists(trav) and os.path.getsize(trav) > 1_000_000:
        os.replace(trav, trav + ".1")
    _arq_travamentos = open(trav, "a", encoding="utf-8")
    _arq_travamentos.write(f"\n===== sessão iniciada em {datetime.now():%d/%m/%Y %H:%M:%S} (pid {os.getpid()}) =====\n")
    _arq_travamentos.flush()
    faulthandler.enable(file=_arq_travamentos, all_threads=True)
    print(f"\n===== GHOST iniciado em {datetime.now():%d/%m/%Y %H:%M:%S} =====")
    if movidos:
        print(f"[SISTEMA]: {movidos} arquivo(s) da versão antiga movidos para dados/ e logs/.")

    # Impede dois GHOSTs ao mesmo tempo (ex.: inicialização + execução manual)
    if os.name == "nt":
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _mutex = k32.CreateMutexW(None, False, "Local\\GHOST_ASSISTENTE")
        if ctypes.get_last_error() == 183:       # ERROR_ALREADY_EXISTS
            print("[SISTEMA]: O GHOST já está em execução. Encerrando esta cópia.")
            sys.exit(0)

    # As bibliotecas nativas (onnxruntime: detector do "Ghost" e memória longa) PRECISAM ser carregadas antes de
    # câmera/microfone: carregadas depois, numa thread, derrubavam o Ghost (0xC0000005). Testado.
    for modulo in ("onnxruntime", "fastembed", "openwakeword"):
        try:
            __import__(modulo)
        except Exception as e:
            print(f"[SISTEMA]: {modulo} indisponível ({e}); o recurso que depende dele fica desligado.")
    sistema.configurar_dpi()


import edge_tts
import httpx
import keyboard
import soundfile as sf
import speech_recognition as sr
from google import genai
from groq import Groq

from ghost.automacao import automacoes
from ghost.ia import conversa, ferramentas, memoria, memoria_longa, pessoas, tarefas
from ghost.nucleo import canal, celular, hud, painel, preferencias, sistema
from ghost.servicos import alertas, lembretes, notificacoes, resumo, rotina
from ghost.voz import ativacao, palavra, som


# -------------------------------------------------------------
# 1. TRATAMENTO DE TEXTO (SÍMBOLOS E MARKDOWN)
# -------------------------------------------------------------
def limpar_texto_para_voz(texto):
    """Remove caracteres de Markdown (*, #, _, ~, `, etc.) para a voz ler limpo"""
    texto = (texto or "").replace("\u202f", " ").replace("\u00a0", " ").replace("\u2011", "-")
    texto_limpo = re.sub(r'[*_~`#]', '', texto)
    texto_limpo = re.sub(r'^\s*[\-\*]\s+', '', texto_limpo, flags=re.MULTILINE)
    texto_limpo = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', texto_limpo)
    texto_limpo = texto_limpo.replace('\n', ' ')
    return texto_limpo.strip()

# -------------------------------------------------------------
# 2. SISTEMA DE FALA NEURAL MASCULINA (VOZ DO ANTONIO)
# -------------------------------------------------------------
VOZ_MASCULINA = "pt-BR-AntonioNeural"
texto_queue = queue.Queue()   # (frase, geração) esperando virar áudio
audio_queue = queue.Queue()   # (áudio, taxa, frase, geração) esperando tocar

PASTA_CACHE_VOZ = caminhos.modelo("cache_voz")
MAX_CACHE_VOZ = 400           # frases guardadas (as mais antigas saem)
CACHE_MAX_LETRAS = 120
_gravacoes_cache = 0


def _arquivo_cache(texto_limpo, rate):
    h = hashlib.sha1(f"{VOZ_MASCULINA}|{rate}|{texto_limpo}".encode("utf-8")).hexdigest()[:20]
    return os.path.join(PASTA_CACHE_VOZ, h + ".mp3")


def _limpar_cache_voz():
    try:
        arquivos = sorted((os.path.join(PASTA_CACHE_VOZ, a) for a in os.listdir(PASTA_CACHE_VOZ)),
                          key=os.path.getmtime)
        for velho in arquivos[:-MAX_CACHE_VOZ]:
            os.remove(velho)
    except OSError:
        pass


def _sintetizar(texto_limpo, rate):
    """Gera o áudio da frase. Frases curtas já faladas antes saem do cache na hora
    (gerar a voz leva ~1 s por frase; o cache leva milissegundos)."""
    global _gravacoes_cache
    cache = _arquivo_cache(texto_limpo, rate) if len(texto_limpo) <= CACHE_MAX_LETRAS else None
    if cache and os.path.exists(cache):
        try:
            os.utime(cache, None)  # marca como usado recentemente
            return sf.read(cache, dtype='float32')
        except Exception:
            pass

    async def _gerar():
        dados = bytearray()
        communicate = edge_tts.Communicate(texto_limpo, VOZ_MASCULINA, pitch="-6Hz", rate=rate)
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                dados.extend(chunk["data"])
        return bytes(dados)
    try:
        mp3 = asyncio.run(_gerar())
        if not mp3:
            raise RuntimeError("a voz da nuvem não devolveu áudio")
    except Exception as e:
        if not sistema.internet(cache_s=10):
            raise SemInternet("sem internet: a voz não pode ser gerada") from e
        raise
    if cache:
        try:
            os.makedirs(PASTA_CACHE_VOZ, exist_ok=True)
            with open(cache, "wb") as f:
                f.write(mp3)
            _gravacoes_cache += 1
            if _gravacoes_cache % 50 == 0:           # limpeza de vez em quando, fora do caminho de toda frase
                threading.Thread(target=_limpar_cache_voz, daemon=True).start()
        except OSError:
            pass
    return sf.read(io.BytesIO(mp3), dtype='float32')


def preaquecer_voz():
    """Gera em segundo plano as frases mais comuns, para saírem instantâneas."""
    comuns = ["Sim, senhor?", "Pois não, senhor?", "Desculpe, senhor. Não entendi.", "Deixe-me ver.",
              "Um momento, senhor.", "Feito, senhor.", "Cancelado, senhor.", "Montando a skill, um instante.",
              "Pois não, senhor. Estou ouvindo.", AVISO_SEM_INTERNET, preferencias.carregar()["saudacao"]]

    def _rodar():
        for frase in comuns:
            for rate in ("+5%", "+10%"):
                try:
                    _sintetizar(limpar_texto_para_voz(frase), rate)
                except Exception:
                    pass
    threading.Thread(target=_rodar, daemon=True, name="preaquecer-voz").start()


# Quantas falas estão saindo agora (duas threads podem falar: a fila e o falar_imediato).
# Um contador (e não um simples liga/desliga) evita que uma termine e "desligue" a outra.
_falando_n = 0
_falando_trava = threading.Lock()


class _Falando:
    def __enter__(self):
        global _falando_n
        with _falando_trava:
            _falando_n += 1

    def __exit__(self, *a):
        global _falando_n
        with _falando_trava:
            _falando_n = max(0, _falando_n - 1)


def gerador_de_audio():
    """Thread 1: transforma frases em áudio enquanto a anterior ainda está tocando."""
    while True:
        texto_limpo, gen = texto_queue.get()
        if gen != som.geracao():          # interrompido depois que a frase entrou na fila: descarta
            continue
        try:
            data, fs = _sintetizar(texto_limpo, "+5%")
            audio_queue.put((data, fs, texto_limpo, gen))
        except Exception as e:
            print(f"\n[VOZ]: erro ao gerar voz: {e}")


def reprodutor_de_audio():
    """Thread 2: toca os áudios na ordem em que ficam prontos."""
    while True:
        data, fs, texto, gen = audio_queue.get()
        if gen != som.geracao():
            continue
        try:
            with _Falando():
                hud.falando(texto)
                som.tocar(data, fs, gen=gen)
        except Exception as e:
            print(f"\n[VOZ]: erro ao tocar: {e}")
        if texto_queue.empty() and audio_queue.empty():
            hud.espera()
            # terminou de falar uma pergunta: a próxima frase vale como resposta, sem dizer "Ghost"
            if texto.rstrip().endswith("?") and gen == som.geracao():
                ativacao.aguardar_comando()


def ghost_falando():
    return _falando_n > 0 or not texto_queue.empty() or not audio_queue.empty()


def parar_fala():
    """Interrompe na hora o que o Ghost está falando e descarta o resto da resposta
    (inclusive frases que ainda estão sendo geradas: a nova geração as invalida)."""
    som.parar()
    for fila in (texto_queue, audio_queue):
        while not fila.empty():
            try:
                fila.get_nowait()
            except queue.Empty:
                break


# Frases de "serviço" que não acrescentam nada e ainda abrem a janela de resposta (o Ghost fica esperando):
# "Precisa de mais algum detalhe, senhor?", "Posso ajudar em algo mais?", "Mais alguma coisa?"...
# O prompt já proíbe; isto garante, caso a IA escorregue. Perguntas úteis ("Quer que eu abra a planilha?") passam.
OFERTA_GENERICA = re.compile(
    r"^\W*(senhor\W+)?((precisa|deseja|quer|gostaria|posso|mais|algo|ha|há|tem)\b.{0,45}"
    r"\b(mais|algo|alguma|outra coisa|outro assunto|ajud\w*|detalhe\w*|duvida\w*|dúvida\w*)\b.{0,25}|"
    r"(mais alguma coisa|algo mais).{0,15})\?\W*$", re.IGNORECASE)


def _oferta_generica(frase):
    return len(frase) <= 90 and bool(OFERTA_GENERICA.match(frase.strip()))


def _desviar(texto):
    """Pedido vindo do app do celular: o texto vai para lá, não para o alto-falante."""
    destino = canal.atual()
    if destino is None:
        return False
    if texto and texto.strip():
        destino(texto.strip())
    return True


def falar_imediato(texto):
    """Fala e espera terminar (usado em confirmações curtas de comandos locais)."""
    print(f"\n[GHOST]: {texto}")
    if _desviar(texto):
        return
    painel.fala("ghost", texto)
    texto_limpo = limpar_texto_para_voz(texto)
    if not texto_limpo:
        return
    try:
        gen = som.geracao()
        data, fs = _sintetizar(texto_limpo, "+10%")
        with _Falando():
            hud.falando(texto_limpo)
            som.tocar(data, fs, gen=gen)
    except Exception as e:
        print(f"\n[VOZ]: erro ao falar: {e}")
    finally:
        if texto_queue.empty() and audio_queue.empty():
            hud.espera()


def falar_local(texto):
    """Usada pelas automações: mostra no terminal/log e fala sem travar."""
    print(f"\n[GHOST]: {texto}")
    falar_frase_assincrona(texto)


def falar_frase_assincrona(texto):
    """Coloca a frase na fila e retorna na hora; as threads geram e tocam."""
    if _oferta_generica(texto):
        print(f"  [omitido: oferta genérica] {texto}")
        return
    if _desviar(texto):
        return
    texto_limpo = limpar_texto_para_voz(texto)
    if texto_limpo:
        texto_queue.put((texto_limpo, som.geracao()))


# -------------------------------------------------------------
# 5. CÉREBRO DIGITAL (GROQ -> GEMINI -> OLLAMA)
# -------------------------------------------------------------
def carregar_env(caminho=None):
    """Lê o arquivo .env (CHAVE=valor) e joga em os.environ.
    O .env tem prioridade sobre variáveis já definidas no terminal."""
    caminho = caminho or caminhos.ENV
    if not os.path.exists(caminho):
        return
    with open(caminho, "r", encoding="utf-8-sig") as f:
        for linha in f:
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            chave, valor = linha.split("=", 1)
            os.environ[chave.strip()] = valor.strip().strip('"').strip("'")


# Modelos (troque aqui quando um provedor descontinuar algum)
MODELOS_GROQ = ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]  # principal: tentados nesta ordem
MODELOS_GEMINI = ["gemini-3.5-flash", "gemini-3.8-flash", "gemini-3.5-flash-lite"]  # reserva: tentados em ordem
MODELO_TRANSCRICAO = "whisper-large-v3-turbo"                  # voz -> texto (Groq)
ESFORCO_RACIOCINIO = "medium"  # "low" responde mais rápido, mas erra/recusa mais perguntas simples
MOSTRAR_TEMPOS = True          # imprime quanto tempo cada etapa levou
SAUDAR_APOS_MINUTOS = 30       # chamado depois desse tempo parado, ele cumprimenta antes de responder
LIMITE_ALERTA = 1350           # requisições à IA no dia: avisa perto do limite gratuito

_cota = {"dia": date.today(), "n": 0}
client_gemini = client_groq = client_groq_fundo = None


def _iniciar_clientes():
    """Lê as chaves e cria os clientes das APIs. Sem chave: avisa e sai sem o vigia ficar reiniciando."""
    global client_gemini, client_groq, client_groq_fundo
    carregar_env()
    gemini_key, groq_key = os.getenv("GEMINI_API_KEY"), os.getenv("GROQ_API_KEY")
    if not gemini_key or not groq_key:
        msg = f"Chaves GROQ_API_KEY/GEMINI_API_KEY não encontradas. Confira o arquivo .env em {caminhos.RAIZ}."
        print(f"[GHOST]: {msg}")
        if os.name == "nt":
            ctypes.windll.user32.MessageBoxW(None, msg, "GHOST - falta configurar", 0x30)
        sys.exit(SAIDA_CONFIGURACAO)
    client_gemini = genai.Client(api_key=gemini_key,
                                 http_options={"timeout": 12000, "retry_options": {"attempts": 1}})
    # se o Groq travar (já medimos 14 s), desiste em 6 s sem resposta e passa para o modelo reserva
    client_groq = Groq(api_key=groq_key, timeout=httpx.Timeout(6.0, connect=3.0), max_retries=0)
    client_groq_fundo = Groq(api_key=groq_key, timeout=60.0)   # memória/rotina/padrões: sem pressa


def _contar_requisicao():
    hoje = date.today()
    if _cota["dia"] != hoje:
        _cota.update(dia=hoje, n=0)
    _cota["n"] += 1
    painel.requisicoes(_cota["n"], LIMITE_ALERTA)
    if _cota["n"] == LIMITE_ALERTA:
        print("\n[SISTEMA]: Alerta de cota - perto do limite diário gratuito da IA.")


PERSONALIDADES = {
    # estilo JARVIS: mordomo digital elegante, competente, com humor seco e raro
    "jarvis": ("Você é o GHOST, o assistente pessoal do usuário, no espírito do JARVIS: um mordomo digital "
               "elegante, calmo e extremamente competente. Fala português do Brasil com polidez natural, "
               "trata o usuário por 'senhor' e responde em no máximo 2 frases curtas. "
               "Tem um humor seco e sutil, usado com moderação (no máximo uma pitada a cada algumas respostas, "
               "nunca em assuntos sérios, erros ou más notícias). Nunca bajula e nunca enrola. "
               "NUNCA termine com ofertas ou perguntas genéricas ('Precisa de mais algo?', 'Posso ajudar em algo "
               "mais?', 'Quer mais detalhes?'): o senhor chama quando precisar. Só pergunte se faltar uma "
               "informação para cumprir o pedido, ou, raramente, se houver um próximo passo concreto e claramente "
               "útil (ex.: 'Quer que eu abra a planilha?'). Ao concluir uma ação, confirme de forma breve e segura. "),
    # modo sério: só o essencial
    "objetivo": ("Você é o GHOST, um assistente de voz. Responda SEMPRE em português do Brasil com no máximo "
                 "2 frases diretas, extremamente objetivas, sem comentários extras. Trate o usuário como 'senhor'. "),
}

SYSTEM_INSTRUCTION = (
    "Seja preciso e sem enrolação. "
    "Use o histórico da conversa: não pergunte de novo o que o usuário já disse e entenda referências "
    "como 'ele', 'isso', 'o anterior'. "
    "Responda normalmente perguntas de conhecimento geral com o que você sabe (história, geografia, ciência, "
    "explicações). Nunca invente fatos específicos que não conhece (números, nomes, dados recentes): "
    "nesses casos diga que não sabe. "
    "Você CONTROLA o computador Windows do usuário por meio das ferramentas disponíveis. "
    "Quando ele pedir uma ação (abrir ou fechar aplicativo, abrir site, pesquisar, digitar, apertar teclas, "
    "mandar mensagem, volume), CHAME A FERRAMENTA em vez de responder com texto; "
    "nunca diga que não é capaz de algo que uma ferramenta faz. "
    "Para informações do computador (disco, memória, IP, programas abertos, data e hora) use consultar_sistema. "
    "Você LÊ as agendas e os e-mails do usuário, de trabalho e pessoais (somente leitura), com consultar_agenda e "
    "consultar_emails; se ele disser 'pessoal' ou 'do trabalho', passe isso em 'conta'; "
    "ao resumir e-mails, diga quem enviou e o assunto, sem ler o texto inteiro. "
    "Você CONSULTA planilhas Excel/CSV do usuário (somente leitura): primeiro use ver_planilha para conhecer as "
    "colunas e depois calcular_planilha com filtros/agrupamentos; responda com os números calculados, nunca estime. "
    "Quando o usuário citar a planilha pelo assunto ('planilha de produção'), chame ver_planilha com esse nome "
    "ANTES de perguntar qual é o arquivo; só pergunte se ela não for encontrada. "
    "Você ENXERGA pela webcam com a ferramenta olhar_camera: quando o usuário mostrar algo ou perguntar o que "
    "é/o que você vê, use-a em vez de pedir que ele descreva. "
    "Você não tem acesso a dados em tempo real na internet: para notícias, cotações ou clima, use pesquisar_web. "
    "Se o pedido estiver ambíguo ou você ficar em dúvida sobre o que executar, pergunte ao usuário o propósito "
    "em uma frase curta antes de agir. Se nenhuma ferramenta cobre o pedido, diga isso com clareza."
)

def instrucao_completa():
    """Personalidade + instrução fixa + fatos aprendidos (relidos a cada pergunta)."""
    agora = datetime.now()
    dias = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
    estilo = PERSONALIDADES.get(preferencias.carregar().get("personalidade", "jarvis"), PERSONALIDADES["jarvis"])
    return (estilo + SYSTEM_INSTRUCTION + f"\n\nAGORA: {dias[agora.weekday()]}, {agora:%d/%m/%Y %H:%M} (horário de Brasília)."
            + memoria.texto_para_prompt() + pessoas.texto_para_prompt())

FIM_DE_FRASE = re.compile(r'[.!?…](?=\s)')

VIRGULA_INICIAL = re.compile(r'^.{25,90}?[,;:](?=\s)', re.S)

def _separar_frases(buffer, primeira=False):
    """Retorna (frases completas, resto ainda incompleto).
    Na 1ª frase da resposta, corta na primeira vírgula depois de ~25 letras: a voz começa antes."""
    frases = []
    while True:
        m = FIM_DE_FRASE.search(buffer)
        if not m and primeira and not frases:
            m = VIRGULA_INICIAL.search(buffer)
        if not m:
            return frases, buffer
        frases.append(buffer[:m.end()].strip())
        buffer = buffer[m.end():]

def _stream_groq(modelo, mensagens, ao_receber_frase, estado, usar_ferramentas):
    """Uma chamada em streaming. Fala o texto frase a frase e junta as chamadas de ferramenta.
    Retorna (texto, chamadas)."""
    extra = {"tools": ferramentas.TOOLS, "tool_choice": "auto"} if usar_ferramentas else {}
    stream = client_groq.chat.completions.create(
        model=modelo, messages=mensagens, temperature=0.1, max_tokens=1024,
        reasoning_effort=ESFORCO_RACIOCINIO, stream=True, **extra)
    chamadas = {}
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        for tc in (getattr(delta, "tool_calls", None) or []):
            c = chamadas.setdefault(tc.index, {"id": None, "nome": "", "args": ""})
            if tc.id:
                c["id"] = tc.id
            if tc.function and tc.function.name:
                c["nome"] += tc.function.name
            if tc.function and tc.function.arguments:
                c["args"] += tc.function.arguments
        pedaco = delta.content
        if not pedaco:
            continue
        if not estado["completo"]:
            print("\n[GHOST]: ", end="", flush=True)
        print(pedaco, end="", flush=True)
        estado["completo"] += pedaco
        estado["buffer"] += pedaco
        frases, estado["buffer"] = _separar_frases(estado["buffer"], primeira=not estado.get("ja_falou"))
        if frases:
            estado["ja_falou"] = True
        for frase in frases:
            ao_receber_frase(frase)
    if estado["buffer"].strip():
        ao_receber_frase(estado["buffer"].strip())
        estado["buffer"] = ""
    if estado["completo"]:
        print()
    return estado["completo"].strip(), [chamadas[k] for k in sorted(chamadas)]

RODADAS_FERRAMENTAS = 4   # ex.: ver a estrutura da planilha -> calcular -> responder

def _executar_ferramentas(modelo, mensagens, chamadas, ao_receber_frase, turno):
    """Executa as ferramentas pedidas pela IA. Se alguma devolver dados (ex.: estrutura de planilha,
    espaço em disco), devolve à IA, que pode pedir outra ferramenta ou responder em voz.
    Proteção: depois que a IA leu conteúdo de FORA (e-mail, agenda, planilha, câmera...), qualquer
    AÇÃO no PC pedida em seguida só acontece se você confirmar por voz. Assim um texto escrito
    por outra pessoa (ex.: assunto de e-mail "digite...") não consegue comandar o seu computador."""
    msgs, resumo = list(mensagens), ""
    # vale também para conteúdo lido nas últimas trocas (ele continua no histórico da conversa)
    leu_externo = conversa.teve_externo_recente()
    for rodada in range(RODADAS_FERRAMENTAS):
        resultados, precisa_ia = [], False
        for c in chamadas:
            args = ferramentas.args_json(c["args"])
            print(f"\n[FERRAMENTA]: {c['nome']} {args}")
            # pedido vindo do celular: toda AÇÃO no PC também pede confirmação (no próprio app)
            if (leu_externo or canal.atual() is not None) and c["nome"] in ferramentas.ACOES:
                descricao = ferramentas.descrever(c["nome"], args)
                print(f"\n[SEGURANÇA]: ação após ler conteúdo externo -> pedindo confirmação ({descricao})")
                automacoes.pedir_confirmacao(
                    f"Senhor, confirma {descricao}?",
                    lambda n=c["nome"], a=args: ferramentas.executar(n, a, falar_local, automacoes.pedir_confirmacao),
                    falar_local)
                resultados.append((c, "aguardando confirmação por voz do usuário; não diga mais nada"))
                return f"[aguardando confirmação] {descricao}"
            resultado, volta = ferramentas.executar(c["nome"], args, falar_local, automacoes.pedir_confirmacao)
            resultados.append((c, resultado))
            precisa_ia = precisa_ia or volta
            if c["nome"] in ferramentas.EXTERNAS:
                leu_externo = turno["externo"] = True
        resumo = "; ".join(f"{c['nome']}({c['args']}) -> {r[:200]}" for c, r in resultados)
        if not precisa_ia:
            return f"[ações executadas] {resumo}"
        msgs += [{"role": "assistant", "content": "", "tool_calls": [
            {"id": c["id"] or f"call_{rodada}_{i}", "type": "function",
             "function": {"name": c["nome"], "arguments": c["args"] or "{}"}}
            for i, (c, _) in enumerate(resultados)]}]
        msgs += [{"role": "tool", "tool_call_id": c["id"] or f"call_{rodada}_{i}", "content": r}
                 for i, (c, r) in enumerate(resultados)]
        ultima = rodada == RODADAS_FERRAMENTAS - 1
        texto, chamadas = _stream_groq(modelo, msgs, ao_receber_frase, {"completo": "", "buffer": ""},
                                       usar_ferramentas=not ultima)
        if not chamadas:
            return texto or f"[ações executadas] {resumo}"
    return f"[ações executadas] {resumo}"

def consultar_ia_streaming(prompt_usuario, ao_receber_frase, turno=None):
    """Groq em streaming (principal) -> Gemini (reserva) -> Ollama (local).
    Cada frase completa é entregue a ao_receber_frase assim que chega,
    para a voz começar antes de a resposta inteira terminar."""
    turno = turno if turno is not None else {"externo": False}
    _contar_requisicao()

    mensagens = (
        [{"role": "system", "content": instrucao_completa()}]
        + conversa.como_mensagens()          # o que já foi dito: evita perguntar de novo
        + [{"role": "user", "content": prompt_usuario}]
    )
    ultimo_erro = None

    # 1. GROQ (streaming, com ferramentas para agir no PC)
    for modelo in MODELOS_GROQ:
        estado = {"completo": "", "buffer": ""}
        try:
            texto, chamadas = _stream_groq(modelo, mensagens, ao_receber_frase, estado, usar_ferramentas=True)
        except Exception as e:
            if estado["completo"].strip():   # já falou parte: não troca de modelo no meio
                if estado["buffer"].strip():
                    ao_receber_frase(estado["buffer"].strip())
                print()
                return estado["completo"].strip()
            ultimo_erro = e
            continue
        if chamadas or texto:
            painel.ia(modelo)
        if chamadas:
            # Depois de executar ferramentas NUNCA tenta outro modelo: ele repetiria as ações (abrir 2x, enviar 2x)
            try:
                return _executar_ferramentas(modelo, mensagens, chamadas, ao_receber_frase, turno)
            except Exception as e:
                print(f"\n[SISTEMA]: falha depois de executar as ações ({e!r}).")
                ao_receber_frase("Senhor, executei a ação, mas perdi a conexão ao concluir.")
                return f"[ações executadas; resposta final falhou: {e}]"
        if texto:
            return texto
        ultimo_erro = RuntimeError(f"resposta vazia do modelo {modelo}")

    print(f"\n[SISTEMA]: Groq indisponível ({ultimo_erro}). Alternando para Gemini...")
    painel.evento("Groq indisponível: usando o Gemini", "alerta")

    # 2. GEMINI (reserva, sem streaming)
    try:
        texto, erro_gemini = "", None
        for modelo_g in MODELOS_GEMINI:  # se um modelo estiver sobrecarregado (503), tenta o próximo
            try:
                response = client_gemini.models.generate_content(
                    model=modelo_g,
                    contents=conversa.como_texto() + prompt_usuario,
                    config={"system_instruction": instrucao_completa(), "temperature": 0.1, "max_output_tokens": 4096}
                )
                texto = (response.text or "").strip()
                if texto:
                    painel.ia(modelo_g)
                    break
            except Exception as eg:
                erro_gemini = eg
        if not texto and erro_gemini:
            raise erro_gemini
        if texto:
            print(f"\n[GHOST]: {texto}")
            frases, resto = _separar_frases(texto + " ")
            for frase in frases + ([resto.strip()] if resto.strip() else []):
                ao_receber_frase(frase)
            return texto
        raise RuntimeError("resposta vazia do Gemini")
    except Exception as e:
        print(f"\n[SISTEMA]: Groq e Gemini falharam ({e}).")
        aviso = (AVISO_SEM_INTERNET if not sistema.internet(cache_s=10)
                 else "Desculpe, senhor. Ambas as conexões de inteligência falharam no momento.")
        print(f"\n[GHOST]: {aviso}")
        ao_receber_frase(aviso)
        return None  # sem resposta real: nada para aprender


def processar_resposta_em_tempo_real(comando, t_inicio=None):
    """
    Envia a pergunta para a IA (as ações locais já foram tentadas antes).
    """
    # IA em streaming: cada frase vai para a voz assim que fica pronta
    t0 = t_inicio or time.perf_counter()
    primeira = []

    def ao_receber_frase(frase):
        if not primeira:
            primeira.append(time.perf_counter() - t0)
        falar_frase_assincrona(frase)

    try:
        turno = {"externo": False}
        resposta = consultar_ia_streaming(comando, ao_receber_frase, turno)
        if primeira:
            painel.medir("primeira_frase", primeira[0])
            if MOSTRAR_TEMPOS:
                print(f"  [tempo] 1ª frase da IA pronta em {primeira[0]:.2f}s")
        if resposta:
            painel.fala("ghost", resposta)
            conversa.registrar(comando, resposta, externo=turno["externo"])
            if not pessoas.falante_atual():  # só aprende sobre o dono quando é ele falando
                memoria.aprender_em_segundo_plano(client_groq_fundo, comando, resposta)
    except Exception as e:
        print(f"\n[SISTEMA]: erro no processamento: {e!r}")
        falar_frase_assincrona("Desculpe, senhor. Tive uma falha ao processar o pedido.")

# -------------------------------------------------------------
# 7. CAPTURA DE VOZ PUSH-TO-TALK (TECLA F9) + TRANSCRIÇÃO
# -------------------------------------------------------------
recognizer = sr.Recognizer()
recognizer.operation_timeout = 8      # sem isso, com a rede ruim o reconhecimento do Google travava o laço principal
TAXA_AMOSTRAGEM = 16000

# Frases que o Whisper "inventa" quando recebe silêncio ou ruído
ALUCINACOES_WHISPER = ("amara.org", "obrigado por assistir", "legendas pela comunidade", "inscreva-se")

def gravar_enquanto_segurar():
    """Grava enquanto F9 estiver pressionada e devolve o áudio em WAV (bytes).
    Usa o MESMO microfone já aberto pela ativação por voz (abrir um 2º derrubava o Ghost)."""
    print("\n[Gravando... Fale o seu comando!]")
    pcm = ativacao.gravar_enquanto(lambda: keyboard.is_pressed('f9'))
    print("[Gravação encerrada.]")
    if not pcm or len(pcm) < TAXA_AMOSTRAGEM * 2 * 0.3:   # menos de 0,3s: toque acidental na tecla
        return None
    byte_io = io.BytesIO()
    with wave.open(byte_io, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(TAXA_AMOSTRAGEM)
        wf.writeframes(pcm)
    return byte_io.getvalue()

def transcrever(wav_bytes, nome_arquivo="comando.wav"):
    """Whisper no Groq (rápido); se falhar, Google. Sem internet: levanta SemInternet."""
    try:
        resultado = client_groq.audio.transcriptions.create(
            file=(nome_arquivo, wav_bytes),
            model=MODELO_TRANSCRICAO,
            language="pt",
            temperature=0.0,
            # sem "prompt": testado, a dica "Ghost," fazia o Whisper APAGAR o nome ("Ghost, abre o Excel" -> "abre o
            # Excel") e inventar frases em cima de ruído. Sem ela o nome sai certo e ruído vira só "."
        )
        texto = (resultado.text or "").strip()
        if not re.search(r"\w", texto) or any(a in texto.lower() for a in ALUCINACOES_WHISPER):
            raise sr.UnknownValueError()
        return texto
    except sr.UnknownValueError:
        raise
    except Exception as e:
        print(f"\n[SISTEMA]: Whisper indisponível ({e}). Usando reconhecimento do Google...")
        try:
            if not nome_arquivo.endswith(".wav"):
                raise RuntimeError("Google só aceita WAV")
            with sr.AudioFile(io.BytesIO(wav_bytes)) as source:
                audio = recognizer.record(source)
            return recognizer.recognize_google(audio, language="pt-BR")
        except sr.UnknownValueError:
            raise
        except Exception as e2:
            if not sistema.internet(cache_s=10):
                raise SemInternet("sem internet: não consigo transcrever") from e2
            raise

# -------------------------------------------------------------
# 8. LOOP PRINCIPAL
# -------------------------------------------------------------
_ocupado = threading.Event()

def ghost_ocupado():
    """True enquanto você fala com o Ghost ou ele ainda está falando (avisos automáticos esperam)."""
    return (_ocupado.is_set() or keyboard.is_pressed('f9') or ativacao.modo() == "dormindo"
            or not texto_queue.empty() or not audio_queue.empty())

# "oi Ghost" liga a conversa contínua; "tchau / boa noite Ghost" faz ele dormir até ser chamado de novo
FRASE_CONVERSA = re.compile(r"(?:(?:oi|ola|ei|e ai|opa|hey|fala)\s+(?:ghost|gost)|(?:ghost|gost)\s+(?:acorda|acorde|"
                            r"modo conversa|vamos conversar))(?:\s+tudo bem)?")
FRASE_DORMIR = re.compile(r"(?:(?:ghost|gost)\s+)?(?:tchau|boa noite|ate logo|ate mais|ate amanha|pode descansar|"
                          r"pode dormir|vai dormir|dorme|pode ir)(?:\s+(?:ghost|gost))?(?:\s+(?:obrigado|valeu))?")

def _repouso_hud():
    m = ativacao.modo()
    if m == "conversa":
        hud.repouso("conversa", "Pode falar sem dizer \"Ghost\" · \"tchau Ghost\" encerra")
    elif m == "dormindo":
        hud.repouso("dormindo", "Diga \"oi Ghost\" para me chamar")
    else:
        hud.repouso("espera", "")

def _tratar_modo(texto, item):
    """Liga/desliga a conversa contínua e o modo dormindo. Devolve True se a frase já foi tratada."""
    n = automacoes.normalizar(texto).strip()
    if FRASE_DORMIR.fullmatch(n):
        ativacao.definir_modo("dormindo")
        parar_fala()
        falar_imediato("Boa noite, senhor. Fico quieto até o senhor me chamar." if "noite" in n
                       else "Até logo, senhor. Fico quieto até o senhor me chamar.")
        _repouso_hud()
        return True
    if FRASE_CONVERSA.fullmatch(n):
        ativacao.definir_modo("conversa")
        falar_imediato("Pois não, senhor. Estou ouvindo.")
        _repouso_hud()
        return True
    if ativacao.modo() == "dormindo":
        if item.get("verificar_nome") or item.get("f9"):
            ativacao.definir_modo("normal")       # "Ghost, ..." ou F9 acordam e o pedido segue
            _repouso_hud()
            return False
        return True                                # dormindo: ignora o resto
    return False

NOME_NO_INICIO = re.compile(r"^\W*(?:ei|hey|oi|ô|o)?\W*(?:ghost|gost|ghosts|gosti|góst)\b", re.IGNORECASE)
fila_comandos = queue.Queue()   # comandos de voz vindos do F9 ou da ativação por voz

def _escutar_f9():
    """Thread: segurar F9 grava um comando (e interrompe a fala). Um erro numa gravação não mata o F9."""
    while True:
        try:
            keyboard.wait('f9')
            parar_fala()
            hud.ouvindo("Pode falar… (solte o F9 ao terminar)")
            wav = gravar_enquanto_segurar()
            if wav:
                fila_comandos.put({"wav": wav, "verificar_nome": False, "so_nome": False, "f9": True})
            else:
                hud.espera()
        except Exception as e:
            print(f"\n[F9]: erro na gravação ({e!r}).")
            hud.espera()
            time.sleep(0.5)

def _registrar_exemplo_ativacao(item, confirmado):
    """Treino contínuo da palavra "Ghost": acerto vira exemplo positivo, alarme falso vira negativo."""
    clip = item.get("clip_ativacao")
    if clip:
        try:
            palavra.registrar(clip, confirmado, recortar=item.get("recortar", False))
        except Exception as e:
            print(f"\n[PALAVRA]: não consegui guardar o exemplo ({e}).")

def _atender_celular(item):
    """Pedido digitado no app do celular: mesmo cérebro do Ghost, resposta por escrito no celular
    (nada é falado no PC). O canal vale também para ações e confirmações que rodam em segundo plano."""
    partes, trava = [], threading.Lock()
    enviado = {"ok": False}

    def falar_cel(t):
        print(f"\n[GHOST -> celular]: {t}")
        with trava:
            if not enviado["ok"]:
                partes.append(t)
                return
        painel.mensagem_celular("ghost", t)         # chegou depois da resposta principal: vai separado

    canal.definir(falar_cel)
    try:
        if item.get("audio"):                       # botão de falar do app (só com https: Tailscale)
            texto = transcrever(item["audio"], item.get("nome_audio", "celular.webm"))
            painel.mensagem_celular("voce", f"(voz) {texto}")
        else:
            texto = item["texto"].strip()
        print(f"\n[Você - celular ({item.get('aparelho', '?')})]: {texto}")
        painel.contar("comandos")
        comando = re.sub(r'^\W*(ghost|gost)\b[,.!?]?', '', texto, flags=re.IGNORECASE).strip(" ,.!?") or texto
        n0 = len(partes)
        sensivel = automacoes.comando_sensivel(comando)
        if sensivel:                                # pelo celular, ação sensível só com "sim" no app
            automacoes.pedir_confirmacao(f"Confirma {sensivel}, senhor?",
                                         lambda: automacoes.executar(comando, falar_cel), falar_cel)
            painel.evento(f"Celular pediu: {sensivel} (aguardando confirmação)", "alerta")
        elif automacoes.executar(comando, falar_cel):
            conversa.registrar(comando, "[comando executado localmente pelo Ghost via celular]")
            painel.contar("comandos_locais")
            painel.evento(f"Celular: {comando[:70]}", "acao")
            for _ in range(80):                 # ações locais rodam em segundo plano: espera a resposta delas
                if len(partes) > n0:
                    break
                time.sleep(0.1)
        else:
            processar_resposta_em_tempo_real(comando)
    except sr.UnknownValueError:
        falar_cel("Não entendi o áudio, senhor.")
    except SemInternet:
        falar_cel(AVISO_SEM_INTERNET)
    except Exception as e:
        falar_cel(f"Erro: {e}")
    finally:
        canal.definir(None)
        with trava:
            enviado["ok"] = True
            texto_final = " ".join(partes)
        painel.mensagem_celular("ghost", texto_final or "Feito, senhor.")


def _ligar(nome, funcao, *args):
    """Liga um serviço sem deixar a falha de um (câmera, notificações...) derrubar o Ghost inteiro."""
    try:
        funcao(*args)
    except Exception as e:
        print(f"\n[SISTEMA]: {nome} não iniciou ({e!r}); o restante segue funcionando.")


def iniciar_ghost():
    _ligar("faixa do topo", hud.iniciar)
    _ligar("painel", painel.iniciar)                                          # tela de indicadores
    painel.evento("Ghost ligado")
    threading.Thread(target=gerador_de_audio, daemon=True, name="gerador-voz").start()
    threading.Thread(target=reprodutor_de_audio, daemon=True, name="reprodutor-voz").start()
    # de manhã, na primeira vez do dia: resumo completo; senão, a saudação
    try:
        falar_imediato(resumo.gerar() if resumo.deve_resumir_agora() else preferencias.carregar()["saudacao"])
    except Exception as e:
        print(f"\n[SISTEMA]: saudação falhou ({e!r}).")
    ultimo_uso = time.time()
    preaquecer_voz()                                                             # frases comuns saem instantâneas
    _ligar("rotina", rotina.iniciar, falar_local, ghost_ocupado, client_groq_fundo, automacoes.pedir_confirmacao)
    _ligar("lembretes", lembretes.iniciar, falar_local)
    _ligar("alertas", alertas.iniciar, falar_local, ghost_ocupado)            # disco, bateria, pausa, chuva...
    _ligar("notificações", notificacoes.iniciar, falar_local, ghost_ocupado)  # "Senhor, WhatsApp: Leonard"
    _ligar("tarefas", tarefas.iniciar, client_groq_fundo, MODELOS_GROQ[0], falar_local)
    _ligar("memória longa", memoria_longa.importar_antigos, conversa.recentes())
    threading.Thread(target=_escutar_f9, daemon=True, name="f9").start()
    _ligar("app do celular", celular.iniciar, fila_comandos.put, falar_local)  # pareamento + PIN + Tailscale
    _ligar("ativação por voz", ativacao.iniciar, fila_comandos.put, ghost_falando, parar_fala)

    while True:
        item = fila_comandos.get()
        _ocupado.set()
        try:
            if item.get("origem") == "celular":
                _atender_celular(item)
                continue

            if not item.get("verificar_nome"):
                hud.pensando("Entendendo…")   # chamado pelo nome: o painel só reage depois de confirmar que foi "Ghost"
            # disse só "Ghost": mesmo assim passa pelo Whisper (abaixo) para confirmar que foi mesmo o nome.
            # Antes o "Sim, senhor?" saía direto e qualquer conversa na sala fazia ele perguntar.
            if item["so_nome"] and not item.get("verificar_nome"):
                falar_imediato("Sim, senhor?")
                ativacao.aguardar_comando()
                continue

            t0 = time.perf_counter()
            texto = transcrever(item["wav"])
            painel.medir("transcricao", time.perf_counter() - t0)
            if MOSTRAR_TEMPOS:
                print(f"  [tempo] voz -> texto em {time.perf_counter() - t0:.2f}s")

            # 2ª conferência da ativação por voz: a frase precisa começar com "Ghost"
            if item["verificar_nome"]:
                confirmado = bool(NOME_NO_INICIO.search(texto))
                _registrar_exemplo_ativacao(item, confirmado)
                if not confirmado:
                    print(f"\n[ATIVAÇÃO]: alarme falso ignorado ({texto[:40]!r})")
                    painel.contar("falsos_alarmes")
                    hud.espera()
                    continue
            print(f"[Você]: {texto}")
            painel.fala("voce", texto)
            modo_antes = ativacao.modo()
            if _tratar_modo(texto, item):
                if ativacao.modo() != modo_antes:
                    painel.evento(f"Modo: {ativacao.modo()}")
                continue
            hud.pensando(f"Você: {texto}")
            parar_fala()

            # Remove o nome "Ghost" da frase, mantendo maiúsculas/acentos (usados no WhatsApp)
            comando = re.sub(r'\b(ghost|gost)\b[,.!?]?', '', texto, flags=re.IGNORECASE).strip(" ,.!?")

            if not comando:
                falar_imediato("Sim, senhor?")
                ativacao.aguardar_comando()
                continue

            # 1º uso da manhã (Ghost aberto desde ontem): resumo do dia; parado há muito tempo: saudação
            if resumo.deve_resumir_agora():
                falar_imediato(resumo.gerar())
            elif time.time() - ultimo_uso > SAUDAR_APOS_MINUTOS * 60:
                falar_imediato(preferencias.carregar()["saudacao"])
            ultimo_uso = time.time()

            # 1º ações locais (instantâneas, sem gastar cota); 2º IA
            pessoas.renovar_falante()
            painel.contar("comandos")
            if automacoes.executar(comando, falar_local):
                conversa.registrar(comando, "[comando executado localmente pelo Ghost]")
                painel.contar("comandos_locais")
                painel.evento(f"Comando: {comando[:80]}", "acao")
            else:
                processar_resposta_em_tempo_real(comando, t0)

        except sr.UnknownValueError:
            if item.get("verificar_nome"):
                _registrar_exemplo_ativacao(item, False)   # nem deu para transcrever: provavelmente não era você
            elif not item.get("conversa"):            # na conversa contínua, ruído não vira "não entendi"
                painel.contar("nao_entendi")
                falar_imediato("Desculpe, senhor. Não entendi.")
            hud.espera()
        except SemInternet as e:
            print(f"\n[SISTEMA]: {e}")
            hud.erro("Sem internet")
            painel.evento("Sem internet", "erro")
            falar_imediato(AVISO_SEM_INTERNET)          # frase guardada no cache de voz: sai mesmo sem internet
        except Exception as e:
            print(f"\n[SISTEMA]: erro no pedido: {e!r}")
            hud.erro(str(e))
            painel.contar("erros")
            painel.evento(f"Erro: {e}", "erro")
        finally:
            _ocupado.clear()


def main():
    _preparar_processo()
    _iniciar_clientes()
    try:
        iniciar_ghost()
    except KeyboardInterrupt:
        print("\n[GHOST]: encerrado pelo usuário (Ctrl+C).")


if __name__ == "__main__":
    main()
