import os
import sys
from datetime import datetime

# Silencia os avisos internos do MediaPipe/TensorFlow (W0000, INFO...) no terminal
os.environ.setdefault("GLOG_minloglevel", "2")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

PASTA_GHOST = os.path.dirname(os.path.abspath(__file__))
os.chdir(PASTA_GHOST)  # garante caminhos relativos certos ao iniciar com o Windows

# Rodando oculto (pythonw) não existe terminal: tudo vai para ghost.log
class _LogRotativo:
    """ghost.log com limite de tamanho: passou de 2 MB, vira ghost.log.1 (guarda só 1 anterior)."""
    LIMITE = 2_000_000

    def __init__(self, caminho):
        self.caminho, self._n = caminho, 0
        self._f = open(caminho, "a", encoding="utf-8", buffering=1)

    def write(self, texto):
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
        try:
            self._f.flush()
        except Exception:
            pass

    def isatty(self):
        return False


if sys.stdout is None or sys.stderr is None:
    sys.stdout = sys.stderr = _LogRotativo(os.path.join(PASTA_GHOST, "ghost.log"))

# Travamentos dentro de bibliotecas (som, câmera, Vosk) fecham o Python sem mensagem.
# O faulthandler grava em travamentos.log ONDE foi a queda, em todas as threads.
import faulthandler
_caminho_trav = os.path.join(PASTA_GHOST, "travamentos.log")
if os.path.exists(_caminho_trav) and os.path.getsize(_caminho_trav) > 1_000_000:
    os.replace(_caminho_trav, _caminho_trav + ".1")
_arq_travamentos = open(_caminho_trav, "a", encoding="utf-8")
_arq_travamentos.write(f"\n===== sessão iniciada em {datetime.now():%d/%m/%Y %H:%M:%S} (pid {os.getpid()}) =====\n")
_arq_travamentos.flush()
faulthandler.enable(file=_arq_travamentos, all_threads=True)
print(f"\n===== GHOST iniciado em {datetime.now():%d/%m/%Y %H:%M:%S} =====")

# Impede dois GHOSTs ao mesmo tempo (ex.: inicialização + execução manual)
if os.name == "nt":
    import ctypes
    _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\GHOST_ASSISTENTE")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        print("[SISTEMA]: O GHOST já está em execução. Encerrando esta cópia.")
        sys.exit(0)

# As bibliotecas nativas de IA local (onnxruntime, ctranslate2) PRECISAM ser carregadas aqui, antes de
# câmera/MediaPipe/microfone: carregadas depois, numa thread, derrubavam o Ghost (0xC0000005) ao treinar a
# ativação ou ao guardar a memória longa. Testado: carregando antes, não cai.
for _modulo in ("onnxruntime", "ctranslate2", "fastembed", "openwakeword"):
    try:
        __import__(_modulo)
    except Exception as _e:
        print(f"[SISTEMA]: {_modulo} indisponível ({_e}); o recurso que depende dele fica desligado.")

import asyncio
import io
import wave
import re
import queue
import threading
import json
import time
import sounddevice as sd
import soundfile as sf
import speech_recognition as sr
import keyboard
import edge_tts
from google import genai
from groq import Groq

import automacoes
import conversa
import ferramentas
import memoria
import rosto
import pessoas
import preferencias
import rotina
import ativacao
import lembretes
import resumo
import hud
import som
import arquivo
import alertas
import offline
import palavra
import notificacoes
import tarefas
import telegram_bot
import memoria_longa


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
texto_queue = queue.Queue()   # frases esperando virar áudio
audio_queue = queue.Queue()   # áudios prontos esperando tocar

PASTA_CACHE_VOZ = os.path.join(PASTA_GHOST, "modelos", "cache_voz")
MAX_CACHE_VOZ = 400   # frases guardadas (as mais antigas saem)

def _arquivo_cache(texto_limpo, rate):
    import hashlib
    h = hashlib.sha1(f"{VOZ_MASCULINA}|{rate}|{texto_limpo}".encode("utf-8")).hexdigest()[:20]
    return os.path.join(PASTA_CACHE_VOZ, h + ".mp3")

def _sintetizar(texto_limpo, rate):
    """Gera o áudio da frase. Frases curtas já faladas antes saem do cache na hora
    (gerar a voz leva ~1 s por frase; o cache leva milissegundos)."""
    cache = _arquivo_cache(texto_limpo, rate) if len(texto_limpo) <= 120 else None
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
    if not offline.internet_ok():
        return _voz_local(texto_limpo)
    try:
        mp3 = asyncio.run(_gerar())
    except Exception as e:
        offline.marcar_sem_internet()
        print(f"\n[OFFLINE]: voz da nuvem falhou ({e}); usando a voz local.")
        return _voz_local(texto_limpo)
    if cache:
        try:
            os.makedirs(PASTA_CACHE_VOZ, exist_ok=True)
            with open(cache, "wb") as f:
                f.write(mp3)
            arquivos = sorted((os.path.join(PASTA_CACHE_VOZ, a) for a in os.listdir(PASTA_CACHE_VOZ)), key=os.path.getmtime)
            for velho in arquivos[:-MAX_CACHE_VOZ]:
                os.remove(velho)
        except Exception:
            pass
    return sf.read(io.BytesIO(mp3), dtype='float32')

def _voz_local(texto_limpo):
    """Voz Piper (sem internet). Não vai para o cache, para não substituir a voz normal."""
    if not offline.voz_disponivel():
        raise RuntimeError("sem internet e voz local não instalada")
    return offline.sintetizar(texto_limpo)

def preaquecer_voz():
    """Gera em segundo plano as frases mais comuns, para saírem instantâneas."""
    comuns = ["Sim, senhor?", "Pois não, senhor?", "Desculpe, senhor. Não entendi.", "Deixe-me ver.",
              "Um momento, senhor.", "Feito, senhor.", "Cancelado, senhor.", "Montando a skill, um instante.",
              preferencias.carregar()["saudacao"]]
    def _rodar():
        for frase in comuns:
            for rate in ("+5%", "+10%"):
                try:
                    _sintetizar(limpar_texto_para_voz(frase), rate)
                except Exception:
                    pass
    threading.Thread(target=_rodar, daemon=True).start()

_falando = threading.Event()   # True enquanto o Ghost está com som saindo

def gerador_de_audio():
    """Thread 1: transforma frases em áudio enquanto a anterior ainda está tocando."""
    while True:
        texto_limpo = texto_queue.get()
        try:
            data, fs = _sintetizar(texto_limpo, "+5%")
            audio_queue.put((data, fs, texto_limpo))
        except Exception as e:
            print(f"\nErro ao gerar voz: {e}")

def reprodutor_de_audio():
    """Thread 2: toca os áudios na ordem em que ficam prontos."""
    while True:
        data, fs, texto = audio_queue.get()
        try:
            _falando.set()
            hud.falando(texto)
            som.tocar(data, fs)
        except Exception as e:
            print(f"\nErro ao tocar voz: {e}")
        finally:
            _falando.clear()
        if texto_queue.empty() and audio_queue.empty():
            hud.espera()
        # terminou de falar uma pergunta: a próxima frase vale como resposta, sem dizer "Ghost"
        if texto.rstrip().endswith("?") and texto_queue.empty() and audio_queue.empty():
            ativacao.aguardar_comando()

def ghost_falando():
    return _falando.is_set() or not texto_queue.empty() or not audio_queue.empty()

def parar_fala():
    """Interrompe na hora o que o Ghost está falando e descarta o resto da resposta."""
    for fila in (texto_queue, audio_queue):
        while not fila.empty():
            try:
                fila.get_nowait()
            except queue.Empty:
                break
    som.parar()

threading.Thread(target=gerador_de_audio, daemon=True).start()
threading.Thread(target=reprodutor_de_audio, daemon=True).start()

# Pedido vindo do Telegram: o que o Ghost "falaria" vai por escrito para o celular, não para o alto-falante.
# Só vale para a thread que está atendendo o pedido (alertas de outras threads continuam em voz).
_telegram = {"thread": None, "partes": []}

def _desviar_para_telegram(texto):
    if _telegram["thread"] == threading.get_ident():
        if texto and texto.strip():
            _telegram["partes"].append(texto.strip())
        return True
    return False

def falar_imediato(texto):
    """Fala e espera terminar (usado em confirmações curtas de comandos locais)."""
    print(f"\n[GHOST]: {texto}")
    if _desviar_para_telegram(texto):
        return
    texto_limpo = limpar_texto_para_voz(texto)
    if not texto_limpo:
        return
    try:
        data, fs = _sintetizar(texto_limpo, "+10%")
        _falando.set()
        hud.falando(texto_limpo)
        som.tocar(data, fs)
    except Exception as e:
        print(f"\nErro ao gerar voz: {e}")
    finally:
        _falando.clear()
        if texto_queue.empty() and audio_queue.empty():
            hud.espera()

def falar_local(texto):
    """Usada pelas automações: mostra no terminal/log e fala sem travar."""
    print(f"\n[GHOST]: {texto}")
    falar_frase_assincrona(texto)

def falar_frase_assincrona(texto):
    """Coloca a frase na fila e retorna na hora; as threads geram e tocam."""
    if _desviar_para_telegram(texto):
        return
    texto_limpo = limpar_texto_para_voz(texto)
    if texto_limpo:
        texto_queue.put(texto_limpo)

# -------------------------------------------------------------
# 3. GESTOR DE MEMÓRIA PERSISTENTE E HISTÓRICO LOCAL
# -------------------------------------------------------------
ARQUIVO_MEMORIA = "C:\\GHOST\\memoria_ghost.json"

def carregar_historico_memoria():
    if os.path.exists(ARQUIVO_MEMORIA):
        try:
            with open(ARQUIVO_MEMORIA, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def salvar_historico_memoria(historico_lista):
    try:
        arquivo.salvar_json(ARQUIVO_MEMORIA, historico_lista, indent=2)
    except Exception as e:
        print(f"Erro ao salvar memória: {e}")

# -------------------------------------------------------------
# 5. CÉREBRO DIGITAL (REDUNDÂNCIA GEMINI + GROQ)
# -------------------------------------------------------------
def carregar_env(caminho=os.path.join(PASTA_GHOST, ".env")):
    """Lê o arquivo .env (CHAVE=valor) e joga em os.environ.
    O .env tem prioridade sobre variáveis já definidas no terminal."""
    if not os.path.exists(caminho):
        return
    with open(caminho, "r", encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            chave, valor = linha.split("=", 1)
            os.environ[chave.strip()] = valor.strip().strip('"').strip("'")

carregar_env()

GEMINI_KEY = os.getenv("GEMINI_API_KEY")
GROQ_KEY = os.getenv("GROQ_API_KEY")
if not GEMINI_KEY or not GROQ_KEY:
    raise SystemExit("[GHOST]: Chaves não encontradas. Confira o arquivo .env em C:\\GHOST.")

# Modelos (troque aqui quando um provedor descontinuar algum)
MODELOS_GROQ = ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]  # principal: tentados nesta ordem
MODELOS_GEMINI = ["gemini-3.5-flash", "gemini-3.8-flash", "gemini-3.5-flash-lite"]  # reserva: tentados em ordem
MODELO_TRANSCRICAO = "whisper-large-v3-turbo"                  # voz -> texto (Groq)
ESFORCO_RACIOCINIO = "medium"  # "low" responde mais rápido, mas erra/recusa mais perguntas simples
MOSTRAR_TEMPOS = True
SAUDAR_APOS_MINUTOS = 30   # chamado pelo F9 depois desse tempo parado, ele cumprimenta antes de responder  # imprime quanto tempo cada etapa levou

# Contadores e limites locais
REQUISICOES_HOJE = 0
LIMITE_ALERTA = 1350

# Inicialização dos clientes das APIs
client_gemini = genai.Client(api_key=GEMINI_KEY, http_options={"timeout": 30000, "retry_options": {"attempts": 1}})
import httpx
# se o Groq travar (já medimos 14 s), desiste em 6 s sem resposta e passa para o modelo reserva
client_groq = Groq(api_key=GROQ_KEY, timeout=httpx.Timeout(6.0, connect=3.0), max_retries=0)
client_groq_fundo = Groq(api_key=GROQ_KEY, timeout=60.0)   # memória/rotina/padrões: sem pressa

PERSONALIDADES = {
    # estilo JARVIS: mordomo digital elegante, competente, com humor seco e raro
    "jarvis": ("Você é o GHOST, o assistente pessoal do usuário, no espírito do JARVIS: um mordomo digital "
               "elegante, calmo e extremamente competente. Fala português do Brasil com polidez natural, "
               "trata o usuário por 'senhor' e responde em no máximo 2 frases curtas. "
               "Tem um humor seco e sutil, usado com moderação (no máximo uma pitada a cada algumas respostas, "
               "nunca em assuntos sérios, erros ou más notícias). Nunca bajula e nunca enrola. "
               "Quando houver um próximo passo óbvio e útil, ofereça em poucas palavras "
               "(ex.: 'Quer que eu abra a planilha?'). Ao concluir uma ação, confirme de forma breve e segura. "),
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
    "mandar mensagem, volume, gestos, macros), CHAME A FERRAMENTA em vez de responder com texto; "
    "nunca diga que não é capaz de algo que uma ferramenta faz. "
    "Para informações do computador (disco, memória, IP, programas abertos, data e hora) use consultar_sistema. "
    "Você LÊ as agendas e os e-mails do usuário, de trabalho e pessoais (somente leitura), com consultar_agenda e "
    "consultar_emails; se ele disser 'pessoal' ou 'do trabalho', passe isso em 'conta'; "
    "ao resumir e-mails, diga quem enviou e o assunto, sem ler o texto inteiro. "
    "Você CONTROLA aparelhos inteligentes (luzes, tomadas, ar, TV) com controlar_casa e estado_casa, quando "
    "houver aparelhos conectados. "
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

def _executar_ferramentas(modelo, mensagens, chamadas, ao_receber_frase):
    """Executa as ferramentas pedidas pela IA. Se alguma devolver dados (ex.: estrutura de planilha,
    espaço em disco), devolve à IA, que pode pedir outra ferramenta ou responder em voz.
    Proteção: depois que a IA leu conteúdo de FORA (e-mail, agenda, planilha, câmera...), qualquer
    AÇÃO no PC pedida em seguida só acontece se você confirmar por voz. Assim um texto escrito
    por outra pessoa (ex.: assunto de e-mail "digite...") não consegue comandar o seu computador."""
    msgs, resumo = list(mensagens), ""
    leu_externo = False
    for rodada in range(RODADAS_FERRAMENTAS):
        resultados, precisa_ia = [], False
        for c in chamadas:
            args = ferramentas.args_json(c["args"])
            print(f"\n[FERRAMENTA]: {c['nome']} {args}")
            if leu_externo and c["nome"] in ferramentas.ACOES:
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
            leu_externo = leu_externo or c["nome"] in ferramentas.EXTERNAS
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

def consultar_ia_streaming(prompt_usuario, ao_receber_frase):
    """Groq em streaming (principal) -> Gemini (reserva).
    Cada frase completa é entregue a ao_receber_frase assim que chega,
    para a voz começar antes de a resposta inteira terminar."""
    global REQUISICOES_HOJE
    REQUISICOES_HOJE += 1
    if REQUISICOES_HOJE == LIMITE_ALERTA:
        print("\n[SISTEMA]: Alerta de cota - 90% do limite diário atingido.")

    mensagens = (
        [{"role": "system", "content": instrucao_completa()}]
        + conversa.como_mensagens()          # o que já foi dito: evita perguntar de novo
        + [{"role": "user", "content": prompt_usuario}]
    )
    ultimo_erro = None

    # 0. SEM INTERNET: IA local direto (não perde tempo esperando a nuvem)
    if not offline.internet_ok():
        return _ia_local(mensagens[1:], ao_receber_frase)

    # 1. GROQ (streaming, com ferramentas para agir no PC)
    for modelo in MODELOS_GROQ:
        estado = {"completo": "", "buffer": ""}
        try:
            texto, chamadas = _stream_groq(modelo, mensagens, ao_receber_frase, estado, usar_ferramentas=True)
            if chamadas:
                return _executar_ferramentas(modelo, mensagens, chamadas, ao_receber_frase)
            if texto:
                return texto
            ultimo_erro = RuntimeError(f"resposta vazia do modelo {modelo}")
        except Exception as e:
            if estado["completo"].strip():   # já falou parte: não troca de modelo no meio
                if estado["buffer"].strip():
                    ao_receber_frase(estado["buffer"].strip())
                print()
                return estado["completo"].strip()
            ultimo_erro = e

    print(f"\n[SISTEMA]: Groq indisponível ({ultimo_erro}). Alternando para Gemini...")

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
        print(f"\n[SISTEMA]: Groq e Gemini falharam ({e}). Tentando a IA local...")
        if offline.ollama_ok():
            return _ia_local(mensagens[1:], ao_receber_frase)
        aviso = "Desculpe, senhor. Ambas as conexões de inteligência falharam no momento."
        print(f"\n[GHOST]: {aviso}")
        ao_receber_frase(aviso)
        return None  # sem resposta real: nada para aprender


def _ia_local(mensagens_sem_sistema, ao_receber_frase):
    """Ollama no próprio PC (sem ferramentas). Usado sem internet ou com as duas nuvens fora."""
    try:
        if not offline.ollama_ok():
            raise RuntimeError("Ollama não está rodando ou o modelo não foi baixado")
        # prompt CURTO: no processador do notebook cada palavra do prompt custa tempo (o completo levava ~50 s)
        sistema = {"role": "system", "content": (
            "Você é o Ghost, assistente pessoal do Ivan, responsável pelo PCP (Planejamento e Controle da Produção) "
            "da Pedacinho do Sol Alimentos. Trate-o por 'senhor'. Responda em até 3 frases, em português do Brasil. "
            f"Agora: {datetime.now():%d/%m/%Y %H:%M}.")}
        texto = offline.conversar([sistema] + mensagens_sem_sistema[-5:], ao_receber_frase, _separar_frases)
        print(f"\n[GHOST - local]: {texto}")
        return texto or None
    except Exception as e:
        print(f"\n[OFFLINE]: IA local indisponível ({e}).")
        aviso = "Senhor, estou sem internet e a inteligência local não respondeu. Comandos do PC continuam funcionando."
        ao_receber_frase(aviso)
        return None

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
        # Se o Ghost acabou de perguntar "como você está?", a fala vira resposta ao check-in
        prompt = rosto.contexto_para_resposta(comando) or comando
        resposta = consultar_ia_streaming(prompt, ao_receber_frase)
        if MOSTRAR_TEMPOS and primeira:
            print(f"  [tempo] 1ª frase da IA pronta em {primeira[0]:.2f}s")
        if resposta:
            conversa.registrar(comando, resposta)
            if not pessoas.falante_atual():  # só aprende sobre o dono quando é ele falando
                memoria.aprender_em_segundo_plano(client_groq_fundo, comando, resposta)
    except Exception as e:
        print(f"\nErro no processamento: {e}")
        print("\n[GHOST]: Desculpe, senhor. Tive uma falha geral de conexão com os servidores.")

# -------------------------------------------------------------
# 7. CAPTURA DE VOZ PUSH-TO-TALK (TECLA F9) + TRANSCRIÇÃO
# -------------------------------------------------------------
import numpy as np

recognizer = sr.Recognizer()
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

def _transcrever_local(wav_bytes):
    print("\n[OFFLINE]: transcrevendo no próprio PC...")
    texto = offline.transcrever(wav_bytes)
    if not texto or any(a in texto.lower() for a in ALUCINACOES_WHISPER):
        raise sr.UnknownValueError()
    return texto

def transcrever(wav_bytes, nome_arquivo="comando.wav"):
    """Whisper no Groq (rápido); se falhar, Google; sem internet, Whisper local no PC."""
    if not offline.internet_ok():
        return _transcrever_local(wav_bytes)
    try:
        resultado = client_groq.audio.transcriptions.create(
            file=(nome_arquivo, wav_bytes),
            model=MODELO_TRANSCRICAO,
            language="pt",
            temperature=0.0,
            prompt="Ghost,",   # ajuda o Whisper a escrever o nome do assistente corretamente
        )
        texto = (resultado.text or "").strip()
        if not texto or any(a in texto.lower() for a in ALUCINACOES_WHISPER):
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
        except Exception:
            if nome_arquivo.endswith(".wav"):
                offline.marcar_sem_internet()
            return _transcrever_local(wav_bytes)

# -------------------------------------------------------------
# 8. LOOP PRINCIPAL
# -------------------------------------------------------------
_ocupado = threading.Event()

def ghost_ocupado():
    """True enquanto você fala com o Ghost ou ele ainda está falando (o check-in espera)."""
    return (_ocupado.is_set() or keyboard.is_pressed('f9')
            or not texto_queue.empty() or not audio_queue.empty())

NOME_NO_INICIO = re.compile(r"^\W*(?:ei|hey|oi|ô|o)?\W*(?:ghost|gost|ghosts|gosti|góst)\b", re.IGNORECASE)
fila_comandos = queue.Queue()   # comandos de voz vindos do F9 ou da ativação por voz

def _escutar_f9():
    """Thread: segurar F9 continua funcionando como antes (e interrompe a fala)."""
    while True:
        keyboard.wait('f9')
        parar_fala()
        hud.ouvindo("Pode falar… (solte o F9 ao terminar)")
        wav = gravar_enquanto_segurar()
        if wav:
            fila_comandos.put({"wav": wav, "verificar_nome": False, "so_nome": False})

def _registrar_exemplo_ativacao(item, confirmado):
    """Treino contínuo da palavra "Ghost": acerto vira exemplo positivo, alarme falso vira negativo."""
    clip = item.get("clip_ativacao")
    if clip:
        try:
            palavra.registrar(clip, confirmado, recortar=item.get("recortar", False))
        except Exception as e:
            print(f"\n[PALAVRA]: não consegui guardar o exemplo ({e}).")

def _atender_telegram(item):
    """Pedido pelo celular: mesmo cérebro do Ghost, resposta por escrito."""
    _telegram.update(thread=threading.get_ident(), partes=[])
    enviado = {"ok": False}

    def falar_tg(t):
        """Resposta das ações locais (que rodam em outra thread): vai para o Telegram, nunca para a voz."""
        print(f"\n[GHOST -> Telegram]: {t}")
        if enviado["ok"]:
            telegram_bot.enviar(item["chat"], t)        # chegou depois: manda separado
        else:
            _telegram["partes"].append(t)
    try:
        if item.get("audio"):
            texto = transcrever(item["audio"], item.get("nome_audio", "audio.ogg"))
            _telegram["partes"].append(f"(ouvi: {texto})")
        else:
            texto = item["texto"].strip()
        print(f"\n[Você - Telegram]: {texto}")
        comando = re.sub(r'^\W*(ghost|gost)\b[,.!?]?', '', texto, flags=re.IGNORECASE).strip(" ,.!?") or texto
        if automacoes.executar(comando, falar_tg):
            conversa.registrar(comando, "[comando executado localmente pelo Ghost via Telegram]")
            for _ in range(80):                 # ações locais rodam em segundo plano: espera a resposta delas
                if _telegram["partes"]:
                    break
                time.sleep(0.1)
        else:
            processar_resposta_em_tempo_real(comando)
    except sr.UnknownValueError:
        _telegram["partes"].append("Não entendi o áudio, senhor.")
    except Exception as e:
        _telegram["partes"].append(f"Erro: {e}")
    finally:
        partes, _telegram["thread"] = list(_telegram["partes"]), None
        enviado["ok"] = True
        telegram_bot.enviar(item["chat"], "\n".join(partes) or "Feito, senhor.")

def iniciar_ghost():
    hud.iniciar()
    # de manhã, na primeira vez do dia: resumo completo; senão, a saudação
    falar_imediato(resumo.gerar() if resumo.deve_resumir_agora() else preferencias.carregar()["saudacao"])
    ultimo_uso = time.time()
    preaquecer_voz()                                        # frases comuns saem instantâneas
    rosto.iniciar(falar_local, ghost_ocupado, client_groq_fundo)  # leitura facial + check-in periódico
    rotina.iniciar(falar_local, ghost_ocupado, client_groq_fundo, automacoes.pedir_confirmacao)  # aprende a rotina
    lembretes.iniciar(falar_local)                          # lembretes e alarmes
    alertas.iniciar(falar_local, ghost_ocupado)             # avisos proativos (disco, bateria, pausa, chuva...)
    notificacoes.iniciar(falar_local, ghost_ocupado)        # "Senhor, WhatsApp: Leonard"
    tarefas.iniciar(client_groq_fundo, MODELOS_GROQ[0], falar_local)  # tarefas longas em segundo plano
    telegram_bot.iniciar(fila_comandos.put)                 # pedidos pelo celular (se configurado)
    try:
        memoria_longa.importar_antigos(conversa.recentes())  # 1ª vez: começa a memória longa com o que já existe
    except Exception as e:
        print(f"\n[MEMÓRIA LONGA]: {e}")
    threading.Thread(target=_escutar_f9, daemon=True).start()
    ativacao.iniciar(fila_comandos.put, ghost_falando, parar_fala)  # "Ghost, ..." sem F9

    while True:
        item = fila_comandos.get()
        _ocupado.set()
        try:
            if item.get("origem") == "telegram":
                _atender_telegram(item)
                continue

            hud.pensando("Entendendo…")
            if item["so_nome"]:  # disse só "Ghost"
                falar_imediato("Sim, senhor?")
                ativacao.aguardar_comando()
                continue

            t0 = time.perf_counter()
            texto = transcrever(item["wav"])
            if MOSTRAR_TEMPOS:
                print(f"  [tempo] voz -> texto em {time.perf_counter() - t0:.2f}s")

            # 2ª conferência da ativação por voz: a frase precisa começar com "Ghost"
            if item["verificar_nome"]:
                confirmado = bool(NOME_NO_INICIO.search(texto))
                if offline.internet_ok():
                    _registrar_exemplo_ativacao(item, confirmado)   # só aprende com a transcrição boa (nuvem)
                elif not confirmado:
                    confirmado = True   # sem internet o Whisper local às vezes omite o "Ghost": confia no detector
                if not confirmado:
                    print(f"\n[ATIVAÇÃO]: alarme falso ignorado ({texto[:40]!r})")
                    hud.espera()
                    continue
            print(f"[Você]: {texto}")
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
            if automacoes.executar(comando, falar_local):
                conversa.registrar(comando, "[comando executado localmente pelo Ghost]")
            else:
                processar_resposta_em_tempo_real(comando, t0)

        except sr.UnknownValueError:
            if item.get("verificar_nome"):
                _registrar_exemplo_ativacao(item, False)   # nem deu para transcrever: provavelmente não era você
            else:
                falar_imediato("Desculpe, senhor. Não entendi.")
            hud.espera()
        except Exception as e:
            print(f"Erro: {e}")
            hud.erro(str(e))
        finally:
            _ocupado.clear()

if __name__ == "__main__":
    try:
        iniciar_ghost()
    except KeyboardInterrupt:
        print("\n[GHOST]: encerrado pelo usuário (Ctrl+C).")
