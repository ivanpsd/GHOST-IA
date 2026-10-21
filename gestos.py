"""
GHOST - Controle do computador por gestos da mão.

Liga/desliga por voz: "Ghost, ativar gestos" / "Ghost, desativar gestos".
Os gestos e suas ações ficam no cadastro (gestos_cadastro.json), editável
pela tela "Ghost, abrir cadastro de gestos". Alterações valem na hora.
"""
import os
import time
import threading
import ctypes
import ctypes.wintypes as wt

import cv2
import pyautogui

import camera
import gestos_lib as gl

# -------------------------------------------------------------
# CONFIGURAÇÃO (ajuste fino aqui)
# -------------------------------------------------------------
MODO_MONITORES = "todos"   # "todos": a área da mão cobre os dois monitores lado a lado
                           # "um_por_vez": a mão cobre só um monitor; troque com o gesto/voz "outro monitor"
AREA_ATIVA = (0.20, 0.15, 0.80, 0.65)  # região da imagem (x1, y1, x2, y2) que corresponde às telas
SUAVIZACAO = 0.35          # 0..1 — menor = cursor mais estável; maior = mais rápido
ZONA_MORTA_PX = 2
TEMPO_ARRASTAR = 0.5       # pinça segurada além disso = arrastar
CONGELA_CLIQUE = 0.25      # cursor parado no início da pinça (evita o clique "escorregar")
SWIPE_DIST = 0.22          # deslocamento horizontal (fração da imagem) para o deslizar
SWIPE_JANELA = 0.45        # em quantos segundos
SENS_ROLAGEM = 2500
MOSTRAR_JANELA = True
TAMANHO_JANELA = (320, 240)

# -------------------------------------------------------------
# MONITORES
# -------------------------------------------------------------
user32 = ctypes.windll.user32
try:
    user32.SetProcessDPIAware()
except Exception:
    pass

def listar_monitores():
    """Retângulos (esq, topo, dir, base) de cada monitor, da esquerda para a direita."""
    mons = []
    CB = ctypes.WINFUNCTYPE(ctypes.c_int, wt.HMONITOR, wt.HDC, ctypes.POINTER(wt.RECT), wt.LPARAM)
    def cb(h, dc, r, l):
        mons.append((r.contents.left, r.contents.top, r.contents.right, r.contents.bottom))
        return 1
    user32.EnumDisplayMonitors(None, None, CB(cb), 0)
    return sorted(mons) or [(0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))]

MONITORES = listar_monitores()
monitor_atual = 0
for _i, _m in enumerate(MONITORES):
    if _m[0] == 0 and _m[1] == 0:
        monitor_atual = _i  # começa no principal

def mapear_para_tela(nx, ny):
    """Converte a posição da mão (0..1) em pixel. Em 'todos', a largura total é dividida
    proporcionalmente entre os monitores e a altura segue o monitor onde o cursor está."""
    if MODO_MONITORES == "um_por_vez":
        m = MONITORES[monitor_atual]
        return m[0] + nx * (m[2] - m[0] - 1), m[1] + ny * (m[3] - m[1] - 1)
    total = sum(m[2] - m[0] for m in MONITORES)
    pos = nx * total
    for m in MONITORES:
        larg = m[2] - m[0]
        if pos <= larg or m is MONITORES[-1]:
            fx = min(pos / larg, 1.0)
            return m[0] + fx * (larg - 1), m[1] + ny * (m[3] - m[1] - 1)
        pos -= larg

def trocar_monitor(falar=None):
    """Leva o cursor ao centro do próximo monitor (e muda o monitor ativo no modo 'um_por_vez')."""
    global monitor_atual
    monitor_atual = (monitor_atual + 1) % len(MONITORES)
    m = MONITORES[monitor_atual]
    user32.SetCursorPos(int((m[0] + m[2]) / 2), int((m[1] + m[3]) / 2))
    if falar:
        falar(f"Mouse no monitor {monitor_atual + 1}, senhor.")

# -------------------------------------------------------------
# MOUSE E TECLADO
# -------------------------------------------------------------
ESQ_DOWN, ESQ_UP, DIR_DOWN, DIR_UP, RODA = 0x0002, 0x0004, 0x0008, 0x0010, 0x0800

def _mouse(flag, dados=0):
    user32.mouse_event(flag, 0, 0, dados, 0)

def _clique():
    _mouse(ESQ_DOWN); _mouse(ESQ_UP)

def _tecla(combo):
    teclas = [t.strip().lower() for t in combo.replace(" ", "").split("+") if t.strip()]
    if teclas:
        pyautogui.hotkey(*teclas)

# -------------------------------------------------------------
# ESTADO
# -------------------------------------------------------------
camera_ativa = False
_falar = None
_executar_comando = None

def _avisar(texto):
    print(f"\n[GESTOS]: {texto}")
    if _falar:
        try:
            _falar(texto)
        except Exception:
            pass

class Cadastro:
    """Mantém o cadastro em memória e relê sozinho quando o arquivo muda."""
    def __init__(self):
        self.mtime = None
        self.recarregar()

    def recarregar(self):
        cad = gl.carregar_cadastro()
        self.gestos = cad["gestos"]
        self.acoes = {a["id"]: a for a in cad["acoes"]}
        self.mtime = os.path.getmtime(gl.ARQUIVO_CADASTRO)
        self.gravados = [g for g in self.gestos if g.get("tipo") == "gravado" and g.get("ativo", True)]
        self.por_pose = {g["pose"]: g for g in self.gestos if g.get("tipo") == "nativo" and g.get("ativo", True)}

    def verificar(self):
        try:
            if os.path.getmtime(gl.ARQUIVO_CADASTRO) != self.mtime:
                self.recarregar()
                print("\n[GESTOS]: cadastro de gestos recarregado.")
        except OSError:
            pass

def _executar_acao_unica(acao):
    """Ações disparadas uma vez (ao segurar o gesto pelo tempo definido)."""
    if not acao:
        return
    tipo, comp = gl.tipo_efetivo(acao), acao.get("valor", "")
    if tipo == "macro":
        import macros
        threading.Thread(target=macros.executar, args=(acao.get("passos", []), acao.get("ritmo", "original")),
                         daemon=True).start()
    elif tipo in ("clique", "clique_arrastar"):
        _clique()
    elif tipo == "clique_direito":
        _mouse(DIR_DOWN); _mouse(DIR_UP)
    elif tipo == "duplo_clique":
        _clique(); time.sleep(0.05); _clique()
    elif tipo == "trocar_monitor":
        trocar_monitor()
    elif tipo == "tecla" and comp:
        _tecla(comp)
    elif tipo == "comando" and comp and _executar_comando:
        threading.Thread(target=_executar_comando, args=(comp,), daemon=True).start()
    else:
        return
    print(f"\n[GESTOS]: {acao['nome']}")

# -------------------------------------------------------------
# LOOP PRINCIPAL
# -------------------------------------------------------------
def loop_gestos():
    global camera_ativa
    nome_janela = "GHOST - Gestos"
    janela_aberta = False
    try:
        detector = gl.criar_detector_maos()
        cad = Cadastro()
        camera.iniciar("gestos")

        cx, cy = user32.GetSystemMetrics(0) / 2, user32.GetSystemMetrics(1) / 2
        pausado = False
        pinca_ini, arrastando = None, False
        gesto_atual, gesto_desde, gesto_disparou = None, 0.0, False
        hist_pulso, ult_swipe = [], 0.0
        rolagem_y, acum_rolagem = None, 0.0
        ultimo_id, t0, ult_verif = 0, time.monotonic(), 0.0

        while camera_ativa:
            ultimo_id, frame = camera.ler(ultimo_id, timeout=1.0)
            if frame is None:
                if camera.erro and "gestos" in camera.em_uso():
                    _avisar(f"Senhor, {camera.erro}.")
                    break
                continue  # câmera suspensa (ex.: tela de cadastro aberta)
            frame = frame.copy()
            agora = time.monotonic()
            if agora - ult_verif > 2:
                cad.verificar(); ult_verif = agora

            p = gl.detectar(detector, frame, (agora - t0) * 1000)
            rotulo = "sem mão"
            if p is not None:
                tam = gl.tamanho_mao(p)
                # 1º gestos gravados por você; 2º poses nativas
                g, _ = gl.reconhecer_gravado(gl.vetor(p), cad.gravados)
                pose = gl.classificar_nativa(p)
                if g is None:
                    g = cad.por_pose.get(pose)
                gid = g["id"] if g else None
                acao = cad.acoes.get(g.get("acao_id")) if g else None
                tipo = gl.tipo_efetivo(acao)
                rotulo = g["nome"] if g else pose

                if gid != gesto_atual:
                    gesto_atual, gesto_desde, gesto_disparou = gid, agora, False
                segurando = agora - gesto_desde

                # --- PAUSAR funciona mesmo pausado
                if tipo == "pausar" and segurando >= g.get("segurar", 1.0) and not gesto_disparou:
                    gesto_disparou = True
                    pausado = not pausado
                    if arrastando:
                        _mouse(ESQ_UP); arrastando = False
                    _avisar("Gestos pausados." if pausado else "Gestos retomados.")

                if not pausado:
                    # --- PINÇA nativa com clique/arrastar
                    pinca = gl.d(p[4], p[8]) / tam
                    if pinca_ini is None and tipo == "clique_arrastar" and g.get("pose") == "pinca" \
                            and pinca < gl.PINCA_FECHA:
                        pinca_ini = agora
                    elif pinca_ini is not None and pinca > gl.PINCA_ABRE:
                        if arrastando:
                            _mouse(ESQ_UP); arrastando = False
                        else:
                            _clique()
                        pinca_ini = None
                    if pinca_ini is not None and not arrastando and agora - pinca_ini >= TEMPO_ARRASTAR:
                        _mouse(ESQ_DOWN); arrastando = True

                    # --- MOVER (contínuo) — também durante a pinça, para arrastar
                    if tipo == "mouse_mover" or pinca_ini is not None:
                        congelado = pinca_ini is not None and not arrastando and agora - pinca_ini < CONGELA_CLIQUE
                        if not congelado:
                            x1, y1, x2, y2 = AREA_ATIVA
                            nx = min(max((p[8].x - x1) / (x2 - x1), 0), 1)
                            ny = min(max((p[8].y - y1) / (y2 - y1), 0), 1)
                            ax, ay = mapear_para_tela(nx, ny)
                            ncx, ncy = cx + (ax - cx) * SUAVIZACAO, cy + (ay - cy) * SUAVIZACAO
                            if abs(ncx - cx) > ZONA_MORTA_PX or abs(ncy - cy) > ZONA_MORTA_PX:
                                cx, cy = ncx, ncy
                                user32.SetCursorPos(int(cx), int(cy))

                    # --- ROLAR (contínuo)
                    if tipo == "rolar":
                        if rolagem_y is None:
                            rolagem_y = p[8].y
                        acum_rolagem += (rolagem_y - p[8].y) * SENS_ROLAGEM
                        rolagem_y = p[8].y
                        if abs(acum_rolagem) >= 40:
                            _mouse(RODA, int(acum_rolagem)); acum_rolagem = 0.0
                    else:
                        rolagem_y, acum_rolagem = None, 0.0

                    # --- AÇÕES ÚNICAS (segurar o gesto pelo tempo cadastrado)
                    if g and tipo not in ("mouse_mover", "clique_arrastar", "rolar", "pausar", "nada") \
                            and segurando >= g.get("segurar", 0) and not gesto_disparou:
                        gesto_disparou = True
                        _executar_acao_unica(acao)

                    # --- DESLIZAR com a mão aberta (pose nativa)
                    if pose == "aberta":
                        hist_pulso.append((agora, p[0].x))
                        hist_pulso = [(t, x) for t, x in hist_pulso if agora - t <= SWIPE_JANELA]
                        desloc = hist_pulso[-1][1] - hist_pulso[0][1]
                        if abs(desloc) >= SWIPE_DIST and agora - ult_swipe > 1.0:
                            chave = "swipe_direita" if desloc > 0 else "swipe_esquerda"
                            gs = cad.por_pose.get(chave)
                            if gs:
                                _executar_acao_unica(cad.acoes.get(gs.get("acao_id")))
                            ult_swipe, hist_pulso = agora, []
                    else:
                        hist_pulso = []

                if MOSTRAR_JANELA:
                    gl.desenhar_mao(frame, p)
            else:
                gesto_atual = None
                if arrastando:
                    _mouse(ESQ_UP); arrastando = False
                pinca_ini, rolagem_y, hist_pulso = None, None, []

            if MOSTRAR_JANELA:
                if not janela_aberta:
                    cv2.namedWindow(nome_janela, cv2.WINDOW_NORMAL)
                    cv2.resizeWindow(nome_janela, *TAMANHO_JANELA)
                    lw, lh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
                    cv2.moveWindow(nome_janela, lw - TAMANHO_JANELA[0] - 20, lh - TAMANHO_JANELA[1] - 80)
                    try:
                        cv2.setWindowProperty(nome_janela, cv2.WND_PROP_TOPMOST, 1)
                    except Exception:
                        pass
                    janela_aberta = True
                h, w = frame.shape[:2]
                x1, y1, x2, y2 = AREA_ATIVA
                cv2.rectangle(frame, (int(x1 * w), int(y1 * h)), (int(x2 * w), int(y2 * h)), (255, 120, 0), 2)
                status = "PAUSADO" if pausado else ("ARRASTANDO" if arrastando else rotulo.upper())
                cor = (0, 0, 255) if pausado else (0, 255, 0)
                cv2.putText(frame, status[:28], (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, cor, 2)
                cv2.imshow(nome_janela, frame)
                if (cv2.waitKey(1) & 0xFF) == ord("q"):
                    break
                if cv2.getWindowProperty(nome_janela, cv2.WND_PROP_VISIBLE) < 1:
                    break
    except Exception as e:
        _avisar("Senhor, houve uma falha no controle por gestos.")
        print(f"[GESTOS]: erro: {e!r}")
    finally:
        try:
            _mouse(ESQ_UP)  # nunca deixa o botão do mouse preso
        except Exception:
            pass
        camera.parar("gestos")
        if janela_aberta:
            try:
                cv2.destroyWindow(nome_janela); cv2.waitKey(1)
            except Exception:
                pass
        camera_ativa = False

def alternar_camera(ligar=True, falar_callback=None, executar_comando=None):
    """Chamada pelos comandos de voz do automacoes.py."""
    global camera_ativa, _falar, _executar_comando
    _falar = falar_callback
    if executar_comando:
        _executar_comando = executar_comando
    if ligar and not camera_ativa:
        camera_ativa = True
        threading.Thread(target=loop_gestos, daemon=True).start()
        if falar_callback:
            falar_callback("Controle por gestos ativado, senhor.")
    elif not ligar and camera_ativa:
        camera_ativa = False
        if falar_callback:
            falar_callback("Controle por gestos desativado, senhor.")
    elif ligar and falar_callback:
        falar_callback("O controle por gestos já está ativo, senhor.")
