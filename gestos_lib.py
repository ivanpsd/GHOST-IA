"""
GHOST - Base comum dos gestos: detecção da mão, poses nativas,
gestos gravados (cadastro) e ações disponíveis.
Usado pelo gestos.py (Ghost) e pelo cadastro_gestos.py (tela de cadastro).
"""
import os
import json
import math
import uuid
import urllib.request

import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

PASTA_GHOST = os.path.dirname(os.path.abspath(__file__))
PASTA_MODELOS = os.path.join(PASTA_GHOST, "modelos")
ARQUIVO_CADASTRO = os.path.join(PASTA_GHOST, "gestos_cadastro.json")

URL_MAO = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
           "hand_landmarker/float16/latest/hand_landmarker.task")

# Pinça
PINCA_FECHA = 0.28   # distância polegar-dedo (relativa ao tamanho da mão) para fechar a pinça
PINCA_ABRE = 0.40    # para soltar (histerese evita clique duplo falso)

# -------------------------------------------------------------
# MODELO E DETECTOR
# -------------------------------------------------------------
def garantir_modelo(nome_arquivo, url):
    caminho = os.path.join(PASTA_MODELOS, nome_arquivo)
    if not os.path.exists(caminho):
        os.makedirs(PASTA_MODELOS, exist_ok=True)
        print(f"\n[GESTOS]: Baixando o modelo {nome_arquivo} (uma única vez)...")
        urllib.request.urlretrieve(url, caminho + ".tmp")
        os.replace(caminho + ".tmp", caminho)
    return caminho

def criar_detector_maos():
    opcoes = vision.HandLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=garantir_modelo("hand_landmarker.task", URL_MAO)),
        running_mode=vision.RunningMode.VIDEO,
        num_hands=1,
        min_hand_detection_confidence=0.6,
        min_hand_presence_confidence=0.6,
        min_tracking_confidence=0.5,
    )
    return vision.HandLandmarker.create_from_options(opcoes)

def detectar(detector, frame_bgr, ts_ms):
    """Retorna os 21 pontos da mão (ou None)."""
    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    res = detector.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), int(ts_ms))
    return res.hand_landmarks[0] if res.hand_landmarks else None

# -------------------------------------------------------------
# GEOMETRIA E POSES NATIVAS
# -------------------------------------------------------------
PONTA = {"polegar": 4, "indicador": 8, "medio": 12, "anelar": 16, "minimo": 20}
ARTIC = {"indicador": 6, "medio": 10, "anelar": 14, "minimo": 18}
LIGACOES = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10), (10, 11),
            (11, 12), (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (17, 18), (18, 19), (19, 20), (0, 17)]

def d(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)

def tamanho_mao(p):
    return d(p[0], p[9]) or 1e-6

def dedos_levantados(p):
    """Quais dedos estão esticados (independe da rotação da mão)."""
    tam = tamanho_mao(p)
    dedos = {nome: d(p[PONTA[nome]], p[0]) > d(p[ARTIC[nome]], p[0]) * 1.15 for nome in ARTIC}
    dedos["polegar"] = d(p[4], p[5]) / tam > 0.55 and d(p[4], p[17]) > d(p[3], p[17])
    return dedos

POSES_NATIVAS = {
    "mover": "Só o indicador levantado",
    "pinca": "Pinça polegar + indicador",
    "pinca_medio": "Indicador em pé + polegar tocando o médio",
    "rolar": "Indicador + médio levantados",
    "punho": "Punho fechado",
    "joinha": "Joinha (só o polegar para cima)",
    "hang_loose": "Hang loose (polegar + mindinho)",
    "aberta": "Mão aberta parada",
    "swipe_direita": "Mão aberta deslizando para a direita",
    "swipe_esquerda": "Mão aberta deslizando para a esquerda",
}

def classificar_nativa(p):
    """Pose nativa estática da mão (os 'swipes' são detectados pelo movimento, no gestos.py)."""
    dd = dedos_levantados(p)
    tam = tamanho_mao(p)
    i, m, a, mi, pol = dd["indicador"], dd["medio"], dd["anelar"], dd["minimo"], dd["polegar"]
    if i and m and a and mi:
        return "aberta"
    # pinça: polegar no indicador, com o indicador NÃO enrolado na palma (diferencia do punho)
    if d(p[4], p[8]) / tam < PINCA_ABRE and d(p[8], p[5]) / tam >= 0.45 and not (m and a and mi):
        return "pinca"
    # clique direito: indicador em pé + polegar no médio semi-esticado (médio dobrado em repouso não conta)
    if i and d(p[4], p[12]) / tam < PINCA_FECHA and d(p[12], p[9]) / tam > 0.5 and d(p[4], p[8]) / tam > PINCA_ABRE:
        return "pinca_medio"
    if not (i or m or a or mi):
        if pol and p[4].y < p[5].y:
            return "joinha"
        return "punho" if not pol else "outro"
    if pol and mi and not (i or m or a):
        return "hang_loose"
    if i and m and not (a or mi):
        return "rolar"
    if i and not (m or a or mi):
        return "mover"
    return "outro"

# -------------------------------------------------------------
# GESTOS GRAVADOS (comparação com as amostras do cadastro)
# -------------------------------------------------------------
def vetor(p):
    """Formato da mão normalizado: relativo ao pulso e ao tamanho da mão (21 pontos x,y,z)."""
    tam = tamanho_mao(p)
    base = p[0]
    return np.array([[(q.x - base.x) / tam, (q.y - base.y) / tam, (q.z - base.z) / tam * 0.5] for q in p],
                    dtype=np.float32)

def distancia(v1, v2):
    """Distância média por ponto entre dois formatos de mão."""
    return float(np.linalg.norm(np.asarray(v1) - np.asarray(v2), axis=1).mean())

def calcular_limiar(amostras):
    """Quanto o gesto pode variar e ainda ser reconhecido, a partir da própria gravação."""
    a = [np.asarray(x) for x in amostras]
    if len(a) < 2:
        return 0.22
    dists = [distancia(a[i], a[j]) for i in range(len(a)) for j in range(i + 1, len(a))]
    return float(min(max(np.mean(dists) * 3.0, 0.12), 0.30))

def reconhecer_gravado(v, gravados):
    """Retorna (gesto, distância) do gesto gravado mais parecido dentro do limiar, ou (None, None)."""
    melhor, melhor_d = None, None
    for g in gravados:
        if not g.get("ativo", True) or not g.get("amostras"):
            continue
        dmin = min(distancia(v, s) for s in g["amostras"])
        if dmin <= g.get("limiar", 0.22) and (melhor_d is None or dmin < melhor_d):
            melhor, melhor_d = g, dmin
    return melhor, melhor_d

# -------------------------------------------------------------
# AÇÕES DISPONÍVEIS
# -------------------------------------------------------------
# chave: (rótulo na tela de cadastro, precisa de complemento?)
ACOES = {
    "mouse_mover": ("Mover o mouse (contínuo)", False),
    "clique_arrastar": ("Clique / segurar para arrastar (pinça)", False),
    "clique": ("Clique esquerdo", False),
    "clique_direito": ("Clique direito", False),
    "duplo_clique": ("Duplo clique", False),
    "rolar": ("Rolar a página (suba/desça a mão)", False),
    "pausar": ("Pausar / retomar os gestos", False),
    "trocar_monitor": ("Levar o mouse para o outro monitor", False),
    "tecla": ("Tecla ou atalho (ex.: ctrl+c, enter, alt+tab)", True),
    "comando": ("Comando de voz do Ghost (ex.: abrir calculadora)", True),
    "nada": ("Nada (gesto desligado)", False),
}

def separar_acao(acao):
    """'tecla:ctrl+c' -> ('tecla', 'ctrl+c')"""
    tipo, _, comp = (acao or "nada").partition(":")
    return tipo, comp

def descrever_acao(acao):
    tipo, comp = separar_acao(acao)
    rotulo = ACOES.get(tipo, (tipo, False))[0]
    if tipo == "tecla":
        return f"Tecla: {comp}"
    if tipo == "comando":
        return f"Comando: {comp}"
    return rotulo

# -------------------------------------------------------------
# CADASTRO (gestos_cadastro.json)
# -------------------------------------------------------------
PADRAO = [
    {"id": "mover", "pose": "mover", "acao": "mouse_mover", "segurar": 0},
    {"id": "pinca", "pose": "pinca", "acao": "clique_arrastar", "segurar": 0},
    {"id": "pinca_medio", "pose": "pinca_medio", "acao": "clique_direito", "segurar": 0},
    {"id": "rolar", "pose": "rolar", "acao": "rolar", "segurar": 0},
    {"id": "punho", "pose": "punho", "acao": "pausar", "segurar": 1.0},
    {"id": "joinha", "pose": "joinha", "acao": "tecla:enter", "segurar": 0.8},
    {"id": "hang_loose", "pose": "hang_loose", "acao": "tecla:esc", "segurar": 0.8},
    {"id": "aberta", "pose": "aberta", "acao": "nada", "segurar": 0.8},
    {"id": "swipe_direita", "pose": "swipe_direita", "acao": "tecla:alt+tab", "segurar": 0},
    {"id": "swipe_esquerda", "pose": "swipe_esquerda", "acao": "tecla:alt+left", "segurar": 0},
]

def _nativos_padrao():
    return [dict(g, nome=POSES_NATIVAS[g["pose"]], tipo="nativo", ativo=True) for g in PADRAO]

def carregar_cadastro():
    """Lê o cadastro; cria com os padrões se não existir; inclui nativos que faltarem."""
    try:
        with open(ARQUIVO_CADASTRO, "r", encoding="utf-8") as f:
            gestos = json.load(f).get("gestos", [])
    except Exception:
        gestos = []
    ids = {g.get("id") for g in gestos}
    faltando = [g for g in _nativos_padrao() if g["id"] not in ids]
    if faltando or not os.path.exists(ARQUIVO_CADASTRO):
        gestos = faltando + gestos if not gestos else gestos + faltando
        salvar_cadastro(gestos)
    return gestos

def salvar_cadastro(gestos):
    tmp = ARQUIVO_CADASTRO + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"gestos": gestos}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ARQUIVO_CADASTRO)

def restaurar_nativos(gestos):
    """Volta os nativos ao padrão, mantendo os gravados."""
    return _nativos_padrao() + [g for g in gestos if g.get("tipo") == "gravado"]

def novo_gravado(nome, acao, segurar, amostras):
    return {
        "id": "g_" + uuid.uuid4().hex[:8],
        "nome": nome,
        "tipo": "gravado",
        "acao": acao,
        "segurar": segurar,
        "ativo": True,
        "limiar": calcular_limiar(amostras),
        "amostras": [np.round(np.asarray(a), 4).tolist() for a in amostras],
    }

# -------------------------------------------------------------
# DESENHO
# -------------------------------------------------------------
def desenhar_mao(frame, p):
    h, w = frame.shape[:2]
    pts = [(int(q.x * w), int(q.y * h)) for q in p]
    for a, b in LIGACOES:
        cv2.line(frame, pts[a], pts[b], (0, 200, 0), 2)
    for q in pts:
        cv2.circle(frame, q, 4, (0, 255, 255), -1)
