import os
import sys
from datetime import datetime

# Silencia os avisos internos do MediaPipe/TensorFlow (W0000, INFO...) no terminal
os.environ.setdefault("GLOG_minloglevel", "2")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

PASTA_GHOST = os.path.dirname(os.path.abspath(__file__))
os.chdir(PASTA_GHOST)  # garante caminhos relativos certos ao iniciar com o Windows

# Rodando oculto (pythonw) não existe terminal: tudo vai para ghost.log
if sys.stdout is None or sys.stderr is None:
    _log = os.path.join(PASTA_GHOST, "ghost.log")
    if os.path.exists(_log) and os.path.getsize(_log) > 2_000_000:  # limpa acima de ~2 MB
        os.remove(_log)
    sys.stdout = sys.stderr = open(_log, "a", encoding="utf-8", buffering=1)
print(f"\n===== GHOST iniciado em {datetime.now():%d/%m/%Y %H:%M:%S} =====")

# Impede dois GHOSTs ao mesmo tempo (ex.: inicialização + execução manual)
if os.name == "nt":
    import ctypes
    _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\GHOST_ASSISTENTE")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        print("[SISTEMA]: O GHOST já está em execução. Encerrando esta cópia.")
        sys.exit(0)

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
import alertas


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
    mp3 = asyncio.run(_gerar())
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
            sd.play(data, fs)
            sd.wait()
        except Exception:
            pass
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
    try:
        sd.stop()
    except Exception:
        pass

threading.Thread(target=gerador_de_audio, daemon=True).start()
threading.Thread(target=reprodutor_de_audio, daemon=True).start()

def falar_imediato(texto):
    """Fala e espera terminar (usado em confirmações curtas de comandos locais)."""
    print(f"\n[GHOST]: {texto}")
    texto_limpo = limpar_texto_para_voz(texto)
    if not texto_limpo:
        return
    try:
        data, fs = _sintetizar(texto_limpo, "+10%")
        _falando.set()
        hud.falando(texto_limpo)
        sd.play(data, fs)
        sd.wait()
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
        with open(ARQUIVO_MEMORIA, "w", encoding="utf-8") as f:
            json.dump(historico_lista, f, ensure_ascii=False, indent=2)
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
MODELOS_GEMINI = ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-2.5-flash"]  # reserva: tentados em ordem
MODELO_TRANSCRICAO = "whisper-large-v3-turbo"                  # voz -> texto (Groq)
ESFORCO_RACIOCINIO = "medium"  # "low" responde mais rápido, mas erra/recusa mais perguntas simples
MOSTRAR_TEMPOS = True
SAUDAR_APOS_MINUTOS = 30   # chamado pelo F9 depois desse tempo parado, ele cumprimenta antes de responder  # imprime quanto tempo cada etapa levou

# Contadores e limites locais
REQUISICOES_HOJE = 0
LIMITE_ALERTA = 1350

# Inicialização dos clientes das APIs
client_gemini = genai.Client(api_key=GEMINI_KEY)
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
    espaço em disco), devolve à IA, que pode pedir outra ferramenta ou responder em voz."""
    msgs, resumo = list(mensagens), ""
    for rodada in range(RODADAS_FERRAMENTAS):
        resultados, precisa_ia = [], False
        for c in chamadas:
            args = ferramentas.args_json(c["args"])
            print(f"\n[FERRAMENTA]: {c['nome']} {args}")
            resultado, volta = ferramentas.executar(c["nome"], args, falar_local, automacoes.pedir_confirmacao)
            resultados.append((c, resultado))
            precisa_ia = precisa_ia or volta
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
                    config={"system_instruction": instrucao_completa(), "temperature": 0.1, "max_output_tokens": 1024}
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
        print(f"\n[SISTEMA - ERRO CRÍTICO]: Ambas as APIs falharam. Detalhe: {e}")
        aviso = "Desculpe, senhor. Ambas as conexões de inteligência falharam no momento."
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
    """Grava enquanto F9 estiver pressionada e devolve o áudio em WAV (bytes)."""
    print("\n[Gravando... Fale o seu comando!]")
    frames = []

    def callback(indata, frame_count, time_info, status):
        frames.append(indata.copy())

    with sd.InputStream(samplerate=TAXA_AMOSTRAGEM, channels=1, dtype='int16', callback=callback):
        while keyboard.is_pressed('f9'):
            sd.sleep(30)

    print("[Gravação encerrada.]")

    if not frames:
        return None
    audio_data = np.concatenate(frames, axis=0)
    if len(audio_data) < TAXA_AMOSTRAGEM * 0.3:   # menos de 0,3s: toque acidental na tecla
        return None

    byte_io = io.BytesIO()
    with wave.open(byte_io, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(TAXA_AMOSTRAGEM)
        wf.writeframes(audio_data.tobytes())
    return byte_io.getvalue()

def transcrever(wav_bytes):
    """Whisper no Groq (rápido); se falhar, usa o reconhecimento do Google."""
    try:
        resultado = client_groq.audio.transcriptions.create(
            file=("comando.wav", wav_bytes),
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
        with sr.AudioFile(io.BytesIO(wav_bytes)) as source:
            audio = recognizer.record(source)
        return recognizer.recognize_google(audio, language="pt-BR")

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
        ativacao.pausar()
        try:
            wav = gravar_enquanto_segurar()
        finally:
            ativacao.retomar()
        if wav:
            fila_comandos.put({"wav": wav, "verificar_nome": False, "so_nome": False})

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
    threading.Thread(target=_escutar_f9, daemon=True).start()
    ativacao.iniciar(fila_comandos.put, ghost_falando, parar_fala)  # "Ghost, ..." sem F9

    while True:
        item = fila_comandos.get()
        _ocupado.set()
        hud.pensando("Entendendo…")
        try:
            if item["so_nome"]:  # disse só "Ghost"
                falar_imediato("Sim, senhor?")
                ativacao.aguardar_comando()
                continue

            t0 = time.perf_counter()
            texto = transcrever(item["wav"])
            if MOSTRAR_TEMPOS:
                print(f"  [tempo] voz -> texto em {time.perf_counter() - t0:.2f}s")

            # 2ª conferência da ativação por voz: a frase precisa começar com "Ghost"
            if item["verificar_nome"] and not NOME_NO_INICIO.search(texto):
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
            if not item.get("verificar_nome"):
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
