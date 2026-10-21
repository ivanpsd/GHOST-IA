"""
GHOST - Leitura de expressão facial e check-in periódico.

O que faz:
- Lê sua expressão algumas vezes por segundo (sorriso, testa franzida, olhos
  pesados, bocejos, presença na frente do PC). A imagem NUNCA é salva:
  só números de expressão, mantidos em memória.
- A cada INTERVALO_CHECKIN minutos, se você estiver no computador, o Ghost
  pergunta como você está e se precisa de algo, usando a expressão observada.
- Cada check-in vira uma linha em humor_log.jsonl (horário, expressão, sua resposta).
- A cada CHECKINS_PARA_PADRAO respostas, a IA resume padrões do seu
  comportamento e salva na memória de longo prazo (memoria.py).

Importante: expressão facial NÃO é sentimento. Um rosto sério pode ser só
concentração. Por isso o Ghost pergunta em vez de afirmar.
"""
import os
import json
import time
import random
import threading
import ctypes
from collections import deque
from datetime import datetime

import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

import camera
import gestos_lib as gl

# -------------------------------------------------------------
# CONFIGURAÇÃO
# -------------------------------------------------------------
LEITURA_FACIAL_AO_INICIAR = True   # liga a leitura do rosto quando o Ghost abre
INTERVALO_CHECKIN = 10             # minutos entre perguntas "como você está?"
HORARIO_CHECKIN = (8, 20)          # só pergunta entre 8h e 20h
AMOSTRAS_POR_SEGUNDO = 3
JANELA_ANALISE = 10 * 60           # segundos de expressão considerados no check-in
CHECKINS_PARA_PADRAO = 8           # a cada N respostas, resume padrões de comportamento
TEMPO_RESPOSTA = 180               # segundos em que sua próxima fala conta como resposta ao check-in

PASTA_GHOST = os.path.dirname(os.path.abspath(__file__))
ARQUIVO_LOG = os.path.join(PASTA_GHOST, "humor_log.jsonl")
URL_ROSTO = ("https://storage.googleapis.com/mediapipe-models/face_landmarker/"
             "face_landmarker/float16/latest/face_landmarker.task")

# -------------------------------------------------------------
# LEITURA DA EXPRESSÃO
# -------------------------------------------------------------
leitura_ativa = False
_amostras = deque(maxlen=AMOSTRAS_POR_SEGUNDO * JANELA_ANALISE)
_trava = threading.Lock()
_bocejo_inicio, _ult_bocejo = None, 0.0
_bocejos = deque(maxlen=200)

def _media(bs, *nomes):
    return sum(bs.get(n, 0.0) for n in nomes) / len(nomes)

def _registrar(bs, agora):
    """Transforma os 52 'blendshapes' do MediaPipe em poucos sinais legíveis."""
    global _bocejo_inicio, _ult_bocejo
    if bs is None:
        amostra = {"t": agora, "presente": False}
    else:
        amostra = {
            "t": agora, "presente": True,
            "sorriso": _media(bs, "mouthSmileLeft", "mouthSmileRight"),
            "testa": _media(bs, "browDownLeft", "browDownRight"),
            "olhos": _media(bs, "eyeBlinkLeft", "eyeBlinkRight"),
            "boca": bs.get("jawOpen", 0.0),
            "triste": (_media(bs, "mouthFrownLeft", "mouthFrownRight") + bs.get("browInnerUp", 0.0)) / 2,
        }
        # bocejo = boca bem aberta por mais de 1,5 s
        if amostra["boca"] > 0.55:
            _bocejo_inicio = _bocejo_inicio or agora
            if agora - _bocejo_inicio > 1.5 and agora - _ult_bocejo > 8:
                _bocejos.append(agora); _ult_bocejo = agora
        else:
            _bocejo_inicio = None
    with _trava:
        _amostras.append(amostra)

def _loop_leitura():
    global leitura_ativa
    try:
        opcoes = vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=gl.garantir_modelo("face_landmarker.task", URL_ROSTO)),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=1,
            output_face_blendshapes=True,
        )
        detector = vision.FaceLandmarker.create_from_options(opcoes)
        camera.iniciar("rosto")
        ultimo_id, t0, intervalo = 0, time.monotonic(), 1.0 / AMOSTRAS_POR_SEGUNDO
        while leitura_ativa:
            inicio = time.monotonic()
            ultimo_id, frame = camera.ler(ultimo_id, timeout=2.0)
            if frame is None:
                if camera.erro and "rosto" in camera.em_uso():
                    print(f"\n[ROSTO]: {camera.erro}")
                    break
                continue
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            res = detector.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb),
                                            int((time.monotonic() - t0) * 1000))
            bs = None
            if res.face_blendshapes:
                bs = {c.category_name: c.score for c in res.face_blendshapes[0]}
            _registrar(bs, time.time())
            time.sleep(max(0.0, intervalo - (time.monotonic() - inicio)))
    except Exception as e:
        print(f"\n[ROSTO]: falha na leitura facial: {e!r}")
    finally:
        camera.parar("rosto")
        leitura_ativa = False

def ativar_leitura(ligar=True, falar=None):
    global leitura_ativa
    if ligar and not leitura_ativa:
        leitura_ativa = True
        threading.Thread(target=_loop_leitura, daemon=True).start()
        if falar:
            falar("Leitura facial ativada, senhor.")
    elif not ligar and leitura_ativa:
        leitura_ativa = False
        if falar:
            falar("Leitura facial desativada, senhor.")
    elif falar:
        falar("A leitura facial já está " + ("ativa" if ligar else "desligada") + ", senhor.")

def estado_atual(segundos=JANELA_ANALISE):
    """Resumo da expressão nos últimos minutos: (estado, descrição, métricas) ou (None, None, None)."""
    agora = time.time()
    with _trava:
        janela = [a for a in _amostras if agora - a["t"] <= segundos]
    if len(janela) < 10:
        return None, None, None
    presentes = [a for a in janela if a["presente"]]
    m = {"presenca": len(presentes) / len(janela),
         "bocejos": sum(1 for t in _bocejos if agora - t <= segundos)}
    if presentes:
        n = len(presentes)
        m["sorrindo"] = sum(a["sorriso"] > 0.4 for a in presentes) / n
        m["tenso"] = sum(a["testa"] > 0.4 for a in presentes) / n
        m["olhos_pesados"] = sum(a["olhos"] > 0.5 for a in presentes) / n
        m["abatido"] = sum(a["triste"] > 0.35 for a in presentes) / n
    m = {k: round(v, 2) if isinstance(v, float) else v for k, v in m.items()}

    if m["presenca"] < 0.2:
        return "ausente", "pouco tempo na frente do computador", m
    if m["bocejos"] >= 2 or m.get("olhos_pesados", 0) > 0.15:
        return "cansado", f"aparência de cansaço ({m['bocejos']} bocejos, olhos pesados {m.get('olhos_pesados', 0):.0%} do tempo)", m
    if m.get("abatido", 0) > 0.3 and m.get("sorrindo", 0) < 0.1:
        return "abatido", "expressão mais abatida que o normal", m
    if m.get("tenso", 0) > 0.35:
        return "tenso", f"testa franzida {m['tenso']:.0%} do tempo (tensão ou concentração)", m
    if m.get("sorrindo", 0) > 0.25:
        return "bem-humorado", f"sorrindo {m['sorrindo']:.0%} do tempo", m
    return "neutro", "expressão neutra", m

# -------------------------------------------------------------
# CHECK-IN PERIÓDICO
# -------------------------------------------------------------
PERGUNTAS = {
    "cansado": ["Senhor, o senhor parece cansado. Como está se sentindo? Precisa de alguma coisa, talvez uma pausa?",
                "Senhor, notei sinais de cansaço. Está tudo bem? Posso ajudar em algo?"],
    "tenso": ["Senhor, o senhor parece bem concentrado, talvez tenso. Como está? Precisa de alguma coisa?",
              "Senhor, notei a testa franzida há um tempo. Algo o preocupa? Posso ajudar?"],
    "abatido": ["Senhor, o senhor parece um pouco abatido. Está tudo bem? Precisa de algo?"],
    "bem-humorado": ["Senhor, o senhor parece de bom humor. Como está o dia? Precisa de alguma coisa?"],
    "neutro": ["Senhor, como o senhor está? Precisa de alguma coisa?",
               "Senhor, passando para saber como está. Precisa de algo?"],
    None: ["Senhor, como o senhor está? Precisa de alguma coisa?"],
}

checkin_ativo = True
_adiado_ate = 0.0
_ultimo_checkin = time.time()
_pendente = None          # pergunta aguardando resposta
_respostas_desde_padrao = 0

def _segundos_sem_usar_pc():
    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
    li = LASTINPUTINFO(); li.cbSize = ctypes.sizeof(li)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li))
    return (ctypes.windll.kernel32.GetTickCount() - li.dwTime) / 1000.0

def _usuario_presente():
    estado, _, m = estado_atual(120)
    if m is not None and m["presenca"] >= 0.3:
        return True
    return _segundos_sem_usar_pc() < 120  # sem câmera: considera presente se mexeu no PC há < 2 min

def _registrar_log(registro):
    with open(ARQUIVO_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")

def fazer_checkin(falar):
    global _ultimo_checkin, _pendente
    estado, descricao, metricas = estado_atual()
    pergunta = random.choice(PERGUNTAS.get(estado, PERGUNTAS[None]))
    _ultimo_checkin = time.time()
    _pendente = {"t": time.time(), "estado": estado, "descricao": descricao, "metricas": metricas,
                 "pergunta": pergunta}
    print(f"\n[CHECK-IN]: expressão observada -> {estado or 'sem leitura'} {metricas or ''}")
    falar(pergunta)

def _loop_checkin(falar, ocupado):
    global _pendente
    while True:
        time.sleep(30)
        try:
            agora = time.time()
            # pergunta sem resposta há muito tempo: registra e libera
            if _pendente and agora - _pendente["t"] > TEMPO_RESPOSTA:
                _registrar_log(_montar_registro(_pendente, None)); _pendente = None
            if not checkin_ativo or agora < _adiado_ate or _pendente:
                continue
            if not (HORARIO_CHECKIN[0] <= datetime.now().hour < HORARIO_CHECKIN[1]):
                continue
            if agora - _ultimo_checkin < INTERVALO_CHECKIN * 60 or ocupado():
                continue
            if _usuario_presente():
                fazer_checkin(falar)
        except Exception as e:
            print(f"\n[CHECK-IN]: erro: {e!r}")

def iniciar(falar, ocupado, client_groq=None):
    """Chamado pelo ghost.py na abertura."""
    global _cliente
    _cliente = client_groq
    if LEITURA_FACIAL_AO_INICIAR:
        ativar_leitura(True)
    threading.Thread(target=_loop_checkin, args=(falar, ocupado), daemon=True).start()

def adiar(minutos, falar=None):
    global _adiado_ate
    _adiado_ate = time.time() + minutos * 60
    if falar:
        falar(f"Certo, senhor. Não pergunto nada pelos próximos {minutos} minutos.")

def ligar_checkin(ligar, falar=None):
    global checkin_ativo, _adiado_ate, _ultimo_checkin
    checkin_ativo, _adiado_ate = ligar, 0.0
    _ultimo_checkin = time.time()
    if falar:
        falar("Check-ins retomados, senhor." if ligar else "Check-ins pausados, senhor.")

def _montar_registro(p, resposta):
    return {"data": datetime.fromtimestamp(p["t"]).isoformat(timespec="minutes"),
            "dia_semana": datetime.fromtimestamp(p["t"]).strftime("%A"),
            "expressao": p["estado"], "metricas": p["metricas"],
            "pergunta": p["pergunta"], "resposta": resposta}

def contexto_para_resposta(texto_usuario):
    """Se o Ghost acabou de fazer um check-in, transforma a fala em resposta a ele.
    Retorna o prompt para a IA (ou None se não havia check-in pendente)."""
    global _pendente, _respostas_desde_padrao
    p = _pendente
    if not p or time.time() - p["t"] > TEMPO_RESPOSTA:
        return None
    _pendente = None
    _registrar_log(_montar_registro(p, texto_usuario))
    _respostas_desde_padrao += 1
    if _respostas_desde_padrao >= CHECKINS_PARA_PADRAO and _cliente:
        _respostas_desde_padrao = 0
        threading.Thread(target=resumir_padroes, daemon=True).start()
    obs = p["descricao"] or "sem leitura facial disponível"
    return (f"[CHECK-IN] Você perguntou ao usuário: \"{p['pergunta']}\". "
            f"Expressão observada nos últimos minutos (apenas uma estimativa): {obs}. "
            f"Responda com acolhimento e, se ele pedir algo, ajude de forma prática. "
            f"Resposta do usuário: {texto_usuario}")

def descrever_agora():
    estado, descricao, m = estado_atual()
    if estado is None:
        return "Ainda não tenho leitura facial suficiente, senhor."
    return f"Pela sua expressão nos últimos minutos: {descricao}. É só uma estimativa, senhor."

# -------------------------------------------------------------
# APRENDIZADO DE COMPORTAMENTO
# -------------------------------------------------------------
_cliente = None

def resumir_padroes():
    """Lê os últimos check-ins e grava padrões de comportamento na memória de longo prazo."""
    try:
        import memoria
        with open(ARQUIVO_LOG, "r", encoding="utf-8") as f:
            linhas = [json.loads(l) for l in f.readlines()[-60:]]
        resumo = "\n".join(f"{r['data']} ({r['dia_semana']}): expressão={r['expressao']}; "
                           f"resposta={r['resposta'] or '(não respondeu)'}" for r in linhas)
        prompt = ("Abaixo estão check-ins de um assistente com o usuário (horário, expressão facial estimada "
                  "e o que ele respondeu). Identifique até 5 PADRÕES DE COMPORTAMENTO recorrentes "
                  "(ex.: horários em que costuma ficar cansado, o que costuma pedir, como prefere ser abordado). "
                  "Só inclua padrões com evidência em vários registros. Não inclua diagnósticos de saúde. "
                  "Escreva cada padrão em uma frase curta, 3ª pessoa, começando com 'Comportamento:'. "
                  "Responda SOMENTE JSON: {\"padroes\": [\"...\"]}\n\n" + resumo)
        c = _cliente.chat.completions.create(
            model=memoria.MODELO_MEMORIA, messages=[{"role": "user", "content": prompt}],
            temperature=0, max_tokens=800, reasoning_effort="low",
            response_format={"type": "json_object"})
        padroes = json.loads(c.choices[0].message.content).get("padroes", [])
        memoria.substituir_categoria("Comportamento:", [p for p in padroes if isinstance(p, str)])
    except Exception as e:
        print(f"\n[CHECK-IN]: falha ao resumir padrões: {e!r}")
