"""
GHOST - Base comum dos gestos: detecção da mão, poses nativas,
gestos gravados (cadastro) e ações disponíveis.
Usado pelo gestos.py (Ghost) e pelo cadastro_gestos.py (tela de cadastro).
"""
import math
import os
import shutil
import urllib.request
import uuid

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

from ghost.nucleo import arquivo, caminhos

PASTA_MODELOS = caminhos.MODELOS
ARQUIVO_CADASTRO = caminhos.dado("gestos_cadastro.json")

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
        tmp = caminho + ".tmp"
        try:
            with urllib.request.urlopen(url, timeout=30) as r, open(tmp, "wb") as f:   # sem timeout travava sem rede
                shutil.copyfileobj(r, f, 1 << 20)
            os.replace(tmp, caminho)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
    return caminho

def criar_detector_maos(num_maos=1):
    opcoes = vision.HandLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=garantir_modelo("hand_landmarker.task", URL_MAO)),
        running_mode=vision.RunningMode.VIDEO,
        num_hands=num_maos,
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

def detectar_maos(detector, frame_bgr, ts_ms):
    """Todas as mãos vistas (até 2), da esquerda para a direita da imagem espelhada
    (ou seja: [sua mão esquerda, sua mão direita])."""
    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    res = detector.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), int(ts_ms))
    return sorted(res.hand_landmarks or [], key=lambda p: p[0].x)

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
    "duas_afastar": "Duas mãos abertas se afastando",
    "duas_aproximar": "Duas mãos abertas se aproximando",
    "duas_swipe_direita": "Duas mãos abertas deslizando para a direita",
    "duas_swipe_esquerda": "Duas mãos abertas deslizando para a esquerda",
    "duas_pinca_zoom": "Pinça nas duas mãos, afastando/aproximando",
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
# AÇÕES (catálogo próprio, ligado aos gestos pelo id)
# -------------------------------------------------------------
# Tipos de ação:
#   sistema -> comportamento interno (mover mouse, clique, rolar...)
#   tecla   -> tecla ou atalho (valor: "ctrl+c")
#   comando -> frase executada como comando de voz do Ghost (valor: "abrir calculadora")
#   macro   -> sequência gravada de teclas e cliques (passos)
TIPOS_ACAO = {"sistema": "Sistema", "tecla": "Tecla/atalho", "comando": "Comando de voz", "macro": "Macro gravada"}

ACOES_SISTEMA = {
    "mouse_mover": "Mover o mouse (contínuo)",
    "clique_arrastar": "Clique / segurar para arrastar (pinça)",
    "clique": "Clique esquerdo",
    "clique_direito": "Clique direito",
    "duplo_clique": "Duplo clique",
    "rolar": "Rolar a página (suba/desça a mão)",
    "pausar": "Pausar / retomar os gestos",
    "trocar_monitor": "Levar o mouse para o outro monitor",
    "zoom": "Zoom (afaste = aumenta, aproxime = diminui)",
    "nada": "Nada",
}

def _acoes_padrao():
    acoes = [{"id": k, "nome": v, "tipo": "sistema", "valor": k} for k, v in ACOES_SISTEMA.items()]
    acoes += [
        {"id": "a_enter", "nome": "Enter", "tipo": "tecla", "valor": "enter"},
        {"id": "a_esc", "nome": "Esc", "tipo": "tecla", "valor": "esc"},
        {"id": "a_alt_tab", "nome": "Próxima janela (Alt+Tab)", "tipo": "tecla", "valor": "alt+tab"},
        {"id": "a_voltar", "nome": "Voltar (Alt+←)", "tipo": "tecla", "valor": "alt+left"},
        {"id": "a_task_view", "nome": "Visão de tarefas (Win+Tab)", "tipo": "tecla", "valor": "win+tab"},
        {"id": "a_area_trabalho", "nome": "Mostrar área de trabalho (Win+D)", "tipo": "tecla", "valor": "win+d"},
        {"id": "a_desktop_dir", "nome": "Próxima área de trabalho virtual", "tipo": "tecla", "valor": "ctrl+win+right"},
        {"id": "a_desktop_esq", "nome": "Área de trabalho virtual anterior", "tipo": "tecla", "valor": "ctrl+win+left"},
    ]
    return acoes

def nova_acao(nome, tipo, valor="", passos=None, ritmo="original"):
    a = {"id": "a_" + uuid.uuid4().hex[:8], "nome": nome, "tipo": tipo, "valor": valor}
    if tipo == "macro":
        a["passos"], a["ritmo"] = passos or [], ritmo
    return a

def descrever_acao(a):
    if not a:
        return "(nenhuma)"
    if a["tipo"] == "tecla":
        return f"Tecla: {a['valor']}"
    if a["tipo"] == "comando":
        return f"Comando: {a['valor']}"
    if a["tipo"] == "macro":
        from ghost.automacao import macros
        return f"Macro ({macros.resumo(a.get('passos', []))})"
    return ACOES_SISTEMA.get(a["valor"], a["valor"])

def acao_por_id(cad, acao_id):
    for a in cad["acoes"]:
        if a["id"] == acao_id:
            return a
    return None

def tipo_efetivo(a):
    """'mouse_mover', 'clique', ... para ações de sistema; senão o próprio tipo (tecla/comando/macro)."""
    if not a:
        return "nada"
    return a["valor"] if a["tipo"] == "sistema" else a["tipo"]

# -------------------------------------------------------------
# CADASTRO (gestos_cadastro.json) = {"acoes": [...], "gestos": [...]}
# Cada gesto aponta para uma ação pelo campo "acao_id".
# -------------------------------------------------------------
PADRAO = [
    {"id": "mover", "pose": "mover", "acao_id": "mouse_mover", "segurar": 0},
    {"id": "pinca", "pose": "pinca", "acao_id": "clique_arrastar", "segurar": 0},
    {"id": "pinca_medio", "pose": "pinca_medio", "acao_id": "clique_direito", "segurar": 0},
    {"id": "rolar", "pose": "rolar", "acao_id": "rolar", "segurar": 0},
    {"id": "punho", "pose": "punho", "acao_id": "pausar", "segurar": 1.0},
    {"id": "joinha", "pose": "joinha", "acao_id": "a_enter", "segurar": 0.8},
    {"id": "hang_loose", "pose": "hang_loose", "acao_id": "a_esc", "segurar": 0.8},
    {"id": "aberta", "pose": "aberta", "acao_id": "nada", "segurar": 0.8},
    {"id": "swipe_direita", "pose": "swipe_direita", "acao_id": "a_alt_tab", "segurar": 0},
    {"id": "swipe_esquerda", "pose": "swipe_esquerda", "acao_id": "a_voltar", "segurar": 0},
    {"id": "duas_afastar", "pose": "duas_afastar", "acao_id": "a_task_view", "segurar": 0},
    {"id": "duas_aproximar", "pose": "duas_aproximar", "acao_id": "a_area_trabalho", "segurar": 0},
    {"id": "duas_swipe_direita", "pose": "duas_swipe_direita", "acao_id": "a_desktop_dir", "segurar": 0},
    {"id": "duas_swipe_esquerda", "pose": "duas_swipe_esquerda", "acao_id": "a_desktop_esq", "segurar": 0},
    {"id": "duas_pinca_zoom", "pose": "duas_pinca_zoom", "acao_id": "zoom", "segurar": 0},
]

def _nativos_padrao():
    return [dict(g, nome=POSES_NATIVAS[g["pose"]], tipo="nativo", ativo=True) for g in PADRAO]

def _migrar_acao_antiga(cad, texto):
    """Formato antigo: o gesto tinha 'acao': 'tecla:ctrl+c'. Converte para uma ação do catálogo."""
    tipo, _, valor = (texto or "nada").partition(":")
    if tipo in ACOES_SISTEMA:
        return tipo
    for a in cad["acoes"]:
        if a["tipo"] == tipo and a.get("valor") == valor:
            return a["id"]
    a = nova_acao(f"{TIPOS_ACAO.get(tipo, tipo)}: {valor}", tipo, valor)
    cad["acoes"].append(a)
    return a["id"]

def carregar_cadastro():
    """Lê o cadastro, cria com os padrões se não existir, completa itens faltantes e migra o formato antigo."""
    try:
        dados = arquivo.ler_json(ARQUIVO_CADASTRO, None)
        pode_gravar = True
    except arquivo.ArquivoCorrompido:
        # arquivo existe mas não abriu (editado à mão com erro): usa os padrões SEM gravar por cima,
        # para os gestos e macros gravados não se perderem (há uma cópia .corrompido para recuperar)
        dados, pode_gravar = None, False
    existe = dados is not None
    dados = dados if isinstance(dados, dict) else {}
    cad = {"acoes": dados.get("acoes", []), "gestos": dados.get("gestos", [])}
    mudou = not existe or "acoes" not in dados

    ids_acoes = {a["id"] for a in cad["acoes"]}
    for a in _acoes_padrao():
        if a["id"] not in ids_acoes:
            cad["acoes"].append(a); mudou = True
    for g in cad["gestos"]:
        if "acao_id" not in g:
            g["acao_id"] = _migrar_acao_antiga(cad, g.pop("acao", "nada")); mudou = True
    ids_gestos = {g["id"] for g in cad["gestos"]}
    for g in _nativos_padrao():
        if g["id"] not in ids_gestos:
            cad["gestos"].append(g); mudou = True
    if mudou and pode_gravar:
        salvar_cadastro(cad)
    return cad

def salvar_cadastro(cad):
    arquivo.salvar_json(ARQUIVO_CADASTRO, cad)

def restaurar_nativos(cad):
    """Volta os gestos nativos ao padrão, mantendo gravados e ações."""
    ids_acoes = {a["id"] for a in cad["acoes"]}
    cad["acoes"] += [a for a in _acoes_padrao() if a["id"] not in ids_acoes]
    cad["gestos"] = _nativos_padrao() + [g for g in cad["gestos"] if g.get("tipo") == "gravado"]
    return cad

def novo_gravado(nome, acao_id, segurar, amostras):
    return {
        "id": "g_" + uuid.uuid4().hex[:8],
        "nome": nome,
        "tipo": "gravado",
        "acao_id": acao_id,
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
