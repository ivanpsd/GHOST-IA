"""
GHOST - Ativação por voz: diga "Ghost, ..." sem segurar o F9.

Tudo local até entender que é com ele:
1. O áudio do microfone passa pelo cancelamento de eco (eco.py): a voz do próprio
   Ghost é retirada, sobra a sua.
2. "Ghost" é reconhecido por um detector TREINADO NA SUA VOZ (palavra.py), na hora
   em que você fala. Enquanto ele não for treinado ("Ghost, treinar ativação"),
   vale o Vosk offline, que decide no fim da frase.
3. A frase vai para o Whisper, que confere se começa mesmo com "Ghost".
4. Só "Ghost" -> "Sim, senhor?" e a próxima frase vale como comando.
5. Falar por cima enquanto ele fala (com o eco cancelado) faz ele parar e ouvir você.
Depois de uma pergunta do Ghost, a próxima frase também vale como resposta.
O F9 continua funcionando normalmente.
"""
import io
import json
import os
import queue
import threading
import time
import wave

import vosk

from ghost.nucleo import caminhos
from ghost.voz import eco, palavra, som

MODELO = caminhos.modelo("vosk-model-small-en-us-0.15")
MIC_SEM_DADOS_S = 4       # microfone sem mandar áudio por esse tempo = travou (fone tirado, suspensão): reabre
MAX_REABERTURAS = 30      # tentativas seguidas de reabrir o microfone antes de desistir (F9 continua)

ATIVAR_AO_INICIAR = True
TAXA = 16000
ESPERA_COMANDO = 10       # segundos para COMEÇAR a falar depois de "Ghost" ou de uma pergunta dele
MAX_FRASE = 15            # segundos máximos de uma frase
SILENCIO_FIM = 0.9        # segundos de silêncio que encerram a resposta
FALA_MINIMA = 0.4         # menos que isso (tosse, clique) é ignorado
VOLUME_MINIMO = 350       # piso do detector de voz (o limiar real se adapta ao ruído da sala)
FATOR_DONO = 0.45         # resposta mais baixa que 45% do volume normal da SUA voz = outra pessoa/longe: ignora
FATOR_INTERRUPCAO = 0.6   # falar por cima: sua voz (já sem o eco do Ghost) acima de 60% do seu volume normal...
BLOCOS_INTERRUPCAO = 3    # ...por 3 blocos seguidos (0,75 s) -> ele para de falar e ouve você
CONVERSA_MINUTOS = 5      # conversa ativa ("oi Ghost") sem você falar por esse tempo -> volta ao normal

# Modos: "normal"   -> só reage a "Ghost, ..."
#        "conversa" -> ("oi Ghost") toda frase sua vale como pedido, sem dizer o nome
#        "dormindo" -> ("tchau / boa noite Ghost") ignora tudo e não fala sozinho até ser chamado
_modo = "normal"
_conversa_ate = 0.0

_fila_audio = queue.Queue()
_pausado = threading.Event()
_ativo = False
_aguardando_ate = 0.0
_rec = None
_buffer = bytearray()
_pedir_reset = threading.Event()   # limpeza feita pela própria thread do microfone (evita corrida)
_entregar = _falando = _interromper = None
_gravacoes = []                    # F9/treino: cada gravação em andamento recebe os blocos do microfone
_gravacao_trava = threading.Lock()
_geracao = 0                       # cada ligar() cria uma geração; threads antigas percebem e saem
_mic_aberto = threading.Event()    # o microfone da ativação já está ouvindo
_volume_dono = None                # volume típico da sua voz (aprendido nos "Ghost, ..." e no F9)


def _volume_fala(pcm, limiar=VOLUME_MINIMO):
    """Volume médio só dos trechos com voz (ignora as pausas)."""
    import numpy as np
    a = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype=np.int16).astype(np.float32)
    n = len(a) // 4000
    if n == 0:
        return 0.0
    blocos = np.sqrt(np.mean(a[: n * 4000].reshape(n, 4000) ** 2, axis=1))
    voz = blocos[blocos > limiar]
    return float(voz.mean()) if voz.size else 0.0


def _aprender_volume(pcm, limiar=VOLUME_MINIMO):
    global _volume_dono
    v = _volume_fala(pcm, limiar)
    if v > 0:
        _volume_dono = v if _volume_dono is None else _volume_dono * 0.7 + v * 0.3
        try:                                    # guarda para o próximo início (não começa do zero)
            from ghost.nucleo import preferencias
            preferencias.definir("volume_voz", round(_volume_dono))
        except Exception:
            pass


def _carregar_volume():
    global _volume_dono
    try:
        from ghost.nucleo import preferencias
        _volume_dono = preferencias.carregar().get("volume_voz") or None
    except Exception:
        pass


def _para_wav(pcm):
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(TAXA); w.writeframes(pcm)
    return b.getvalue()


def _callback(indata, frames, tempo, status):
    _fila_audio.put(bytes(indata))


def _resetar():
    """Pede à thread do microfone para descartar o que foi ouvido até agora."""
    _pedir_reset.set()


def _executar_reset():
    global _buffer
    _buffer = bytearray()
    if _rec:
        _rec.Reset()
    while not _fila_audio.empty():
        try:
            _fila_audio.get_nowait()
        except queue.Empty:
            break


_ultima_voz = 0.0          # última vez que alguém falou perto do microfone (fora a voz do próprio Ghost)
_em_resposta = False       # gravando uma resposta/comando agora
_interrompivel = None      # função: a fala atual pode ser cortada por voz alta? (avisos não podem)


def segundos_sem_voz():
    return time.time() - _ultima_voz


def janela_aberta():
    """True enquanto o Ghost espera/grava uma resposta (depois de "Ghost" ou de uma pergunta dele)."""
    return _em_resposta or bool(_aguardando_ate and time.time() < _aguardando_ate)


def definir_interrompivel(funcao):
    global _interrompivel
    _interrompivel = funcao


def definir_modo(novo):
    global _modo, _conversa_ate, _aguardando_ate
    _modo = novo
    _conversa_ate = time.time() + CONVERSA_MINUTOS * 60 if novo == "conversa" else 0.0
    _aguardando_ate = 0.0
    _resetar()
    print(f"\n[ATIVAÇÃO]: modo {novo}.")


def modo():
    return _modo


def aguardar_comando(segundos=ESPERA_COMANDO):
    """A próxima frase vale como comando, sem precisar dizer 'Ghost'."""
    global _aguardando_ate
    if _modo == "dormindo":
        return
    _resetar()  # descarta o que foi ouvido enquanto o próprio Ghost falava
    _aguardando_ate = time.time() + segundos
    try:
        from ghost.nucleo import hud
        hud.ouvindo(f"Pode responder… ({int(segundos)} s)")
    except Exception:
        pass


def gravar_enquanto(condicao, maximo=60):
    """F9/treino: grava pelo microfone já aberto enquanto condicao() for verdadeira.
    Várias gravações ao mesmo tempo funcionam (cada uma recebe uma cópia dos blocos)."""
    if not (_ativo and _mic_aberto.is_set()):   # desligada ou ainda carregando o modelo
        return _gravar_sozinho(condicao, maximo)
    minha = bytearray()
    with _gravacao_trava:
        _gravacoes.append(minha)
    inicio = time.time()
    try:
        while condicao() and time.time() - inicio < maximo:
            time.sleep(0.03)
        time.sleep(0.3)                      # pega o último bloco (0,25 s) que ainda estava chegando
    finally:
        with _gravacao_trava:
            _gravacoes.remove(minha)
            pcm = bytes(minha)
        _resetar()
    _aprender_volume(pcm)
    return pcm


def _gravar_sozinho(condicao, maximo):
    """Ativação por voz desligada: abre o microfone só durante o F9."""
    blocos = []
    with som.entrada(samplerate=TAXA, blocksize=1600, dtype="int16", channels=1,
                     callback=lambda d, f, t, s: blocos.append(bytes(d))):
        inicio = time.time()
        while condicao() and time.time() - inicio < maximo:
            time.sleep(0.03)
    return b"".join(blocos)


def pausar():
    _pausado.set()


def retomar():
    _resetar()
    _pausado.clear()


def _hud(func, *args):
    try:
        from ghost.nucleo import hud
        getattr(hud, func)(*args)
    except Exception:
        pass


class _MicTravado(Exception):
    pass


def _loop(geracao):
    """Mantém o microfone vivo: se ele parar (fone tirado, PC voltou da suspensão, erro do driver),
    espera um pouco, relê os dispositivos e reabre. Antes, um erro aqui deixava a ativação morta em silêncio."""
    global _ativo
    falhas = 0
    try:
        while _ativo and geracao == _geracao:
            inicio = time.time()
            try:
                _ouvir(geracao)
            except Exception as e:
                _mic_aberto.clear()
                if not (_ativo and geracao == _geracao):
                    break
                falhas = 1 if time.time() - inicio > 60 else falhas + 1   # funcionou um tempo: zera a conta
                if falhas > MAX_REABERTURAS:
                    print("\n[ATIVAÇÃO]: o microfone não volta; ativação por voz desligada. Use o F9.")
                    break
                print(f"\n[ATIVAÇÃO]: microfone parou ({e!r}); reabrindo ({falhas}/{MAX_REABERTURAS})...")
                time.sleep(min(10, 1 + falhas))
                som.reiniciar_dispositivos()
    finally:
        _mic_aberto.clear()
        if geracao == _geracao:
            _ativo = False


def _ouvir(geracao):
    global _rec, _buffer, _aguardando_ate, _conversa_ate, _ultima_voz, _em_resposta
    import random
    from collections import deque

    import numpy as np
    vosk.SetLogLevel(-1)
    modelo = vosk.Model(MODELO)
    _rec = vosk.KaldiRecognizer(modelo, TAXA, json.dumps(["ghost", "[unk]"]))
    bloco_s = 4000 / TAXA                       # 0,25 s por bloco
    ruido = 300.0                               # ruído de fundo (se adapta sozinho)
    antes = deque(maxlen=3)                     # ~0,75 s antes de começar a falar (não corta a 1ª sílaba)
    janela = deque(maxlen=8)                    # últimos 2 s (detector da palavra e exemplos de treino)
    resposta, falando_s, silencio_s = None, 0.0, 0.0
    origem, clip_ativacao, fala_depois_s = "resposta", None, 0.0
    detector, espera_detector, ultimo_negativo, proxima_carga = None, 0.0, 0.0, 0.0
    sem_dados_desde = time.time()
    voz_seguida_s = 0.0                         # voz "contínua" há muito tempo = ruído novo (TV, ventilador)
    seguidos = 0                                # blocos seguidos com a sua voz enquanto o Ghost fala
    pontos_ultimo = 0.0
    eco_nivel = 0.0                             # quanto da voz do Ghost "vaza" no microfone (aprende sozinho)
    _carregar_volume()

    def carregar_detector():
        try:
            return palavra.Detector() if palavra.pronto() else None
        except Exception as e:
            print(f"\n[PALAVRA]: detector treinado indisponível ({e}); usando o Vosk.")
            return None

    detector = carregar_detector()
    eco.iniciar()
    with som.entrada(samplerate=TAXA, blocksize=4000, dtype="int16", channels=1, callback=_callback):
        _mic_aberto.set()
        print("\n[ATIVAÇÃO]: ouvindo a palavra \"Ghost\" "
              f"({'detector treinado na sua voz' if detector else 'Vosk offline; diga: Ghost, treinar ativação'}).")
        while _ativo and geracao == _geracao:
            if _pedir_reset.is_set():
                _pedir_reset.clear()
                _executar_reset()
                antes.clear()
                resposta, falando_s, silencio_s = None, 0.0, 0.0
                origem, clip_ativacao, fala_depois_s = "resposta", None, 0.0
            try:
                dados = _fila_audio.get(timeout=1)
            except queue.Empty:
                if time.time() - sem_dados_desde > MIC_SEM_DADOS_S:
                    raise _MicTravado("o microfone parou de mandar áudio") from None
                if _aguardando_ate and time.time() > _aguardando_ate and resposta is None:
                    _aguardando_ate = 0.0
                    _hud("espera")
                continue
            sem_dados_desde = time.time()
            dados = eco.limpar_entrada(dados)   # tira a voz do próprio Ghost do microfone
            with _gravacao_trava:
                if _gravacoes:
                    for g in _gravacoes:
                        g.extend(dados)
                    continue
            if _pausado.is_set():
                continue

            amostras = np.frombuffer(dados, dtype=np.int16).astype(np.float32)
            volume = float(np.sqrt(np.mean(amostras ** 2))) if amostras.size else 0.0
            limiar = max(ruido * 3.0, VOLUME_MINIMO)
            tem_voz = volume > limiar
            if not tem_voz and resposta is None:
                ruido = ruido * 0.95 + volume * 0.05
                voz_seguida_s = 0.0
            elif tem_voz:
                voz_seguida_s += bloco_s
                if voz_seguida_s > 8:            # ninguém fala 8 s sem pausa: é barulho novo -> o piso sobe devagar
                    ruido = ruido * 0.97 + volume * 0.03
            janela.append(dados)

            # detector treinado: roda sempre (precisa do fluxo contínuo) e recarrega após novo treino
            if detector is not None and detector.versao != palavra.versao:
                detector = carregar_detector()
            elif detector is None and time.time() > proxima_carga:
                proxima_carga = time.time() + 30       # tenta (re)carregar no máximo a cada 30 s
                if palavra.versao and palavra.pronto():
                    detector = carregar_detector()
            pontos_antes = pontos_ultimo if detector is not None else 0.0
            pontos = detector.processar(dados) if detector is not None else 0.0
            pontos_ultimo = pontos
            # "Ghost" de verdade dura ~0,5 s: exige 2 blocos seguidos acima do limiar (ou 1 muito alto)
            confirmado_det = pontos >= 0.97 or (pontos >= palavra.LIMIAR and pontos_antes >= palavra.LIMIAR)
            falando_agora = bool(_falando and _falando())
            if tem_voz and not falando_agora:
                _ultima_voz = time.time()
            _em_resposta = resposta is not None
            if _modo == "conversa" and resposta is None and time.time() > _conversa_ate:
                definir_modo("normal")
                print("\n[ATIVAÇÃO]: conversa encerrada por falta de uso.")
                _hud("repouso", "espera", "")
            em_conversa = _modo == "conversa" and not falando_agora

            # ---------- "GHOST" pelo detector treinado: reage na hora (com ele falando, quem interrompe
            # é o Vosk ou a sua voz por cima: o detector sozinho não corta a fala, para evitar cortes à toa)
            if (detector is not None and resposta is None and not falando_agora and _modo != "conversa"
                    and confirmado_det and time.time() > espera_detector):
                espera_detector = time.time() + 2.0
                clip_ativacao = b"".join(janela)
                resposta, origem = bytearray(clip_ativacao), "ghost"
                falando_s, silencio_s, fala_depois_s = 0.5, 0.0, 0.0
                _aguardando_ate = time.time() + ESPERA_COMANDO
                print(f"\n[ATIVAÇÃO]: \"Ghost\" detectado ({pontos:.2f}); conferindo...")
                continue

            # ---------- FALAR POR CIMA: enquanto ele fala, volume bem acima do "vazamento" da voz dele
            # (e perto do seu volume normal) por 0,75 s = é você falando -> ele para e ouve.
            # (avisos — mensagem, aparelho novo — não são cortados por voz alta: só por "Ghost" ou F9)
            if (falando_agora and resposta is None and _volume_dono and _modo != "dormindo"
                    and (_interrompivel is None or _interrompivel())):
                if eco_nivel == 0.0:
                    eco_nivel = volume
                elif volume < 1.5 * eco_nivel:
                    eco_nivel = eco_nivel * 0.9 + volume * 0.1
                acima = volume > max(limiar, FATOR_INTERRUPCAO * _volume_dono, 3.0 * eco_nivel)
                seguidos = seguidos + 1 if acima else 0
                if seguidos >= BLOCOS_INTERRUPCAO:
                    seguidos = 0
                    _interromper()
                    print("\n[ATIVAÇÃO]: o senhor falou por cima: parei e estou ouvindo.")
                    resposta = bytearray(b"".join(list(janela)[-(BLOCOS_INTERRUPCAO + 1):]))
                    origem, falando_s, silencio_s = "resposta", BLOCOS_INTERRUPCAO * bloco_s, 0.0
                    _aguardando_ate = time.time() + ESPERA_COMANDO
                    _hud("ouvindo", "Ouvindo…")
                    continue
            else:
                seguidos = 0

            # ---------- MODO RESPOSTA / COMANDO: depois de "Ghost", de "Sim, senhor?", de uma pergunta
            # dele ou de você falar por cima. Detecta a sua voz pelo volume.
            # (dormindo: só termina de gravar um "Ghost, ..." já detectado; janelas de resposta e conversa ficam desligadas)
            if resposta is not None or ((_aguardando_ate or em_conversa) and _modo != "dormindo"):
                if resposta is None:
                    if tem_voz:
                        resposta = bytearray(b"".join(antes)) + dados
                        origem = "conversa" if (em_conversa and not _aguardando_ate) else "resposta"
                        falando_s, silencio_s = bloco_s, 0.0
                        _hud("ouvindo", "Ouvindo…")
                    elif _aguardando_ate and time.time() > _aguardando_ate:
                        _aguardando_ate = 0.0
                        print("\n[ATIVAÇÃO]: janela de resposta encerrada sem fala.")
                        _hud("espera")
                    antes.append(dados)
                    continue
                resposta.extend(dados)
                if tem_voz:
                    falando_s += bloco_s; fala_depois_s += bloco_s; silencio_s = 0.0
                else:
                    silencio_s += bloco_s
                fim = silencio_s >= SILENCIO_FIM or len(resposta) >= MAX_FRASE * TAXA * 2
                if fim:
                    vol = _volume_fala(bytes(resposta), limiar)
                    distante = origem in ("resposta", "conversa") and bool(_volume_dono) and vol < FATOR_DONO * _volume_dono
                    if distante:
                        print(f"\n[ATIVAÇÃO]: voz baixa/distante ignorada (volume {vol:.0f}, "
                              f"o seu costuma ser {_volume_dono:.0f}).")
                    if origem == "ghost":
                        _aguardando_ate = 0.0
                        _aprender_volume(bytes(resposta), limiar)
                        _entregar({"wav": _para_wav(bytes(resposta)), "verificar_nome": True,
                                   "so_nome": fala_depois_s < FALA_MINIMA, "clip_ativacao": clip_ativacao})
                    elif falando_s >= FALA_MINIMA and not distante:
                        _aguardando_ate = 0.0
                        _aprender_volume(bytes(resposta), limiar)
                        if _modo == "conversa":
                            _conversa_ate = time.time() + CONVERSA_MINUTOS * 60
                        _entregar({"wav": _para_wav(bytes(resposta)), "verificar_nome": False, "so_nome": False,
                                   "conversa": origem == "conversa"})
                    elif time.time() < _aguardando_ate:   # foi só um barulho: continua esperando a resposta
                        _hud("ouvindo", "Pode responder…")
                    else:
                        _aguardando_ate = 0.0
                        _hud("espera")
                    resposta, origem, clip_ativacao, fala_depois_s = None, "resposta", None, 0.0
                    _executar_reset()
                    antes.clear()
                continue

            # ---------- MODO NORMAL (Vosk): frases que começam com "Ghost". Com o detector treinado,
            # serve de reserva e de "professor" (frases sem "Ghost" viram exemplos negativos).
            antes.append(dados)
            _buffer.extend(dados)
            if len(_buffer) > MAX_FRASE * TAXA * 2:
                del _buffer[: len(_buffer) - MAX_FRASE * TAXA * 2]

            if _rec.AcceptWaveform(dados):  # fim de uma frase (pausa na fala)
                palavras = json.loads(_rec.Result()).get("text", "").split()
                frase = bytes(_buffer)
                _buffer = bytearray()
                if palavras[:1] == ["ghost"] and time.time() > espera_detector:
                    _aprender_volume(frase, limiar)
                    so_nome = len(palavras) == 1 and len(frase) < 2.5 * TAXA * 2
                    _entregar({"wav": _para_wav(frase), "verificar_nome": True, "so_nome": so_nome,
                               "clip_ativacao": frase, "recortar": True})
                elif ("ghost" not in palavras and not falando_agora and len(frase) >= TAXA * 2
                      and _volume_fala(frase, limiar) > 0 and time.time() - ultimo_negativo > 20
                      and random.random() < 0.5):
                    ultimo_negativo = time.time()      # amostra de "não é Ghost" para o treino contínuo
                    try:
                        palavra.registrar(frase[-palavra.JANELA * 2:], False)
                    except Exception:
                        pass
            else:
                parcial = json.loads(_rec.PartialResult()).get("partial", "").split()
                if parcial[:1] == ["ghost"] and falando_agora:
                    _interromper()  # "Ghost..." enquanto ele fala: para na hora


def _comecar():
    global _ativo, _geracao
    if not os.path.isdir(MODELO):
        print("\n[ATIVAÇÃO]: modelo de voz offline não encontrado; use o F9.")
        return False
    if not _ativo:
        _geracao += 1                      # uma thread antiga que ainda esteja saindo percebe e não continua
        _ativo = True
        threading.Thread(target=_loop, args=(_geracao,), daemon=True, name="microfone").start()
    return True


def iniciar(entregar, falando, interromper):
    """entregar(item): coloca o comando na fila do Ghost.
    falando(): True se o Ghost está falando. interromper(): para a fala."""
    global _entregar, _falando, _interromper
    _entregar, _falando, _interromper = entregar, falando, interromper
    if ATIVAR_AO_INICIAR:
        _comecar()


def ligar(on, falar=None):
    global _ativo, _geracao
    if on:
        ok = _comecar()
        if falar:
            falar("Ativação por voz ligada, senhor." if ok else "Senhor, o modelo de voz offline não está instalado.")
    else:
        _ativo = False
        _geracao += 1
        if falar:
            falar("Ativação por voz desligada. Use o F9, senhor.")
