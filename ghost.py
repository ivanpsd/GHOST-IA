import os
import sys
from datetime import datetime

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


# -------------------------------------------------------------
# 1. TRATAMENTO DE TEXTO (SÍMBOLOS E MARKDOWN)
# -------------------------------------------------------------
def limpar_texto_para_voz(texto):
    """Remove caracteres de Markdown (*, #, _, ~, `, etc.) para a voz ler limpo"""
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

def _sintetizar(texto_limpo, rate):
    """Gera o áudio da frase direto na memória (sem gravar arquivo em disco)."""
    async def _gerar():
        dados = bytearray()
        communicate = edge_tts.Communicate(texto_limpo, VOZ_MASCULINA, pitch="-6Hz", rate=rate)
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                dados.extend(chunk["data"])
        return bytes(dados)
    mp3 = asyncio.run(_gerar())
    return sf.read(io.BytesIO(mp3), dtype='float32')

def gerador_de_audio():
    """Thread 1: transforma frases em áudio enquanto a anterior ainda está tocando."""
    while True:
        texto_limpo = texto_queue.get()
        try:
            audio_queue.put(_sintetizar(texto_limpo, "+5%"))
        except Exception as e:
            print(f"\nErro ao gerar voz: {e}")

def reprodutor_de_audio():
    """Thread 2: toca os áudios na ordem em que ficam prontos."""
    while True:
        data, fs = audio_queue.get()
        try:
            sd.play(data, fs)
            sd.wait()
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
        sd.play(data, fs)
        sd.wait()
    except Exception as e:
        print(f"\nErro ao gerar voz: {e}")

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
MODELO_GEMINI = "gemini-3.8-flash"                             # reserva
MODELO_TRANSCRICAO = "whisper-large-v3-turbo"                  # voz -> texto (Groq)
MOSTRAR_TEMPOS = True  # imprime quanto tempo cada etapa levou

# Contadores e limites locais
REQUISICOES_HOJE = 0
LIMITE_ALERTA = 1350

# Inicialização dos clientes das APIs
client_gemini = genai.Client(api_key=GEMINI_KEY)
client_groq = Groq(api_key=GROQ_KEY)

SYSTEM_INSTRUCTION = (
    "Você é o GHOST, um assistente de voz ultra-inteligente estilo JARVIS. "
    "Responda SEMPRE em português do Brasil com no máximo 2 frases diretas. "
    "Seja extremamente objetivo, preciso e sem enrolação. "
    "Trate o usuário como 'senhor'. "
    "Nunca invente fatos. Se não souber, diga que não sabe. "
    "Você não tem acesso à internet nem a dados em tempo real (notícias, cotações, clima, horários): "
    "se a pergunta depender disso, diga que não tem essa informação atualizada."
)

FIM_DE_FRASE = re.compile(r'[.!?…](?=\s)')

def _separar_frases(buffer):
    """Retorna (frases completas, resto ainda incompleto)."""
    frases = []
    while True:
        m = FIM_DE_FRASE.search(buffer)
        if not m:
            return frases, buffer
        frases.append(buffer[:m.end()].strip())
        buffer = buffer[m.end():]

def consultar_ia_streaming(prompt_usuario, ao_receber_frase):
    """Groq em streaming (principal) -> Gemini (reserva).
    Cada frase completa é entregue a ao_receber_frase assim que chega,
    para a voz começar antes de a resposta inteira terminar."""
    global REQUISICOES_HOJE
    REQUISICOES_HOJE += 1
    if REQUISICOES_HOJE == LIMITE_ALERTA:
        print("\n[SISTEMA]: Alerta de cota - 90% do limite diário atingido.")

    mensagens = [
        {"role": "system", "content": SYSTEM_INSTRUCTION},
        {"role": "user", "content": prompt_usuario},
    ]
    ultimo_erro = None

    # 1. GROQ (streaming)
    for modelo in MODELOS_GROQ:
        completo, buffer = "", ""
        try:
            stream = client_groq.chat.completions.create(
                model=modelo,
                messages=mensagens,
                temperature=0.1,
                max_tokens=1024,          # folga para o raciocínio interno do gpt-oss
                reasoning_effort="low",   # resposta rápida, adequada para voz
                stream=True,
            )
            for chunk in stream:
                if not chunk.choices:
                    continue
                pedaco = chunk.choices[0].delta.content
                if not pedaco:
                    continue
                if not completo:
                    print("\n[GHOST]: ", end="", flush=True)
                print(pedaco, end="", flush=True)
                completo += pedaco
                buffer += pedaco
                frases, buffer = _separar_frases(buffer)
                for frase in frases:
                    ao_receber_frase(frase)
            if buffer.strip():
                ao_receber_frase(buffer.strip())
            if completo.strip():
                print()
                return completo.strip()
            ultimo_erro = RuntimeError(f"resposta vazia do modelo {modelo}")
        except Exception as e:
            if completo.strip():          # já falou parte: não troca de modelo no meio
                if buffer.strip():
                    ao_receber_frase(buffer.strip())
                print()
                return completo.strip()
            ultimo_erro = e

    print(f"\n[SISTEMA]: Groq indisponível ({ultimo_erro}). Alternando para Gemini...")

    # 2. GEMINI (reserva, sem streaming)
    try:
        response = client_gemini.models.generate_content(
            model=MODELO_GEMINI,
            contents=prompt_usuario,
            config={"system_instruction": SYSTEM_INSTRUCTION, "temperature": 0.1, "max_output_tokens": 1024}
        )
        texto = (response.text or "").strip()
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
        return aviso


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
        consultar_ia_streaming(comando, ao_receber_frase)
        if MOSTRAR_TEMPOS and primeira:
            print(f"  [tempo] 1ª frase da IA pronta em {primeira[0]:.2f}s")
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
def iniciar_ghost():
    falar_imediato("GHOST.")

    while True:
        keyboard.wait('f9')

        try:
            wav = gravar_enquanto_segurar()
            if wav:
                t0 = time.perf_counter()
                texto = transcrever(wav)
                if MOSTRAR_TEMPOS:
                    print(f"  [tempo] voz -> texto em {time.perf_counter() - t0:.2f}s")
                print(f"[Você]: {texto}")

                # Remove o nome "Ghost" da frase, mantendo maiúsculas/acentos (usados no WhatsApp)
                comando = re.sub(r'\b(ghost|gost)\b[,.!?]?', '', texto, flags=re.IGNORECASE).strip(" ,.!?")

                if not comando:
                    falar_imediato("Sim, senhor?")
                    continue

                # 1º ações locais (instantâneas, sem gastar cota); 2º IA
                if not automacoes.executar(comando, falar_local):
                    processar_resposta_em_tempo_real(comando, t0)

        except sr.UnknownValueError:
            falar_imediato("Desculpe, senhor. Não entendi.")
        except Exception as e:
            print(f"Erro: {e}")

if __name__ == "__main__":
    iniciar_ghost()
