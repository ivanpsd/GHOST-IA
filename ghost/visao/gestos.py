"""
GHOST - Controle do computador por gestos da mão.

Liga/desliga por voz: "Ghost, ativar gestos" / "Ghost, desativar gestos".
Os gestos e suas ações ficam no cadastro (gestos_cadastro.json), editável
pela tela "Ghost, abrir cadastro de gestos". Alterações valem na hora.
"""
import ctypes
import ctypes.wintypes as wt
import os
import threading
import time

import cv2
import pyautogui

from ghost.nucleo import sistema
from ghost.visao import camera
from ghost.visao import gestos_lib as gl

# O canto da tela NÃO deve abortar as ações: o "punho fechado = pausar" já é o freio do controle por gestos.
# (Com o FAILSAFE ligado, o mouse num canto fazia qualquer tecla lançar erro e derrubar o controle.)
pyautogui.FAILSAFE = False

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
MAO_PRINCIPAL = "direita"  # mão que move o mouse quando as duas estão na câmera
DUAS_DIST = 0.20           # quanto as mãos precisam afastar/aproximar (fração da imagem)
DUAS_SWIPE = 0.25          # deslocamento das duas mãos juntas para o lado
DUAS_JANELA = 0.5          # em quantos segundos
PASSO_ZOOM = 0.04          # variação da distância entre as pinças para 1 passo de zoom
MOSTRAR_JANELA = True
TAMANHO_JANELA = (320, 240)

# -------------------------------------------------------------
# MONITORES
# -------------------------------------------------------------
user32 = ctypes.windll.user32
sistema.configurar_dpi()

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

def _zoom(passos):
    """Ctrl + roda do mouse: funciona em navegador, Office, imagens, mapas..."""
    user32.keybd_event(0x11, 0, 0, 0)
    _mouse(RODA, 120 * passos)
    user32.keybd_event(0x11, 0, 2, 0)

def _centro_pinca(p):
    return ((p[4].x + p[8].x) / 2, (p[4].y + p[8].y) / 2)

def _processar_duas_maos(maos, cad, agora, e):
    """Gestos com as duas mãos. Retorna True se um gesto de duas mãos está em andamento
    (aí o mouse de uma mão fica parado nesse quadro)."""
    pe, pd = maos
    pose_e, pose_d = gl.classificar_nativa(pe), gl.classificar_nativa(pd)

    # ZOOM: pinça nas duas mãos
    gz = cad.por_pose.get("duas_pinca_zoom")
    if pose_e == "pinca" and pose_d == "pinca" and gz:
        (ax, ay), (bx, by) = _centro_pinca(pe), _centro_pinca(pd)
        dist = ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5
        if e["zoom_ref"] is None:
            e["zoom_ref"] = dist
        passos = int((dist - e["zoom_ref"]) / PASSO_ZOOM)
        if passos and gl.tipo_efetivo(cad.acoes.get(gz["acao_id"])) == "zoom":
            _zoom(passos)
            e["zoom_ref"] += passos * PASSO_ZOOM
        e["rotulo"] = "ZOOM"
        return True
    e["zoom_ref"] = None

    # AFASTAR / APROXIMAR / DESLIZAR com as duas mãos abertas
    if pose_e == "aberta" and pose_d == "aberta":
        dist = abs(pd[0].x - pe[0].x)
        centro = (pd[0].x + pe[0].x) / 2
        e["hist"].append((agora, dist, centro))
        e["hist"] = [h for h in e["hist"] if agora - h[0] <= DUAS_JANELA]
        dd = e["hist"][-1][1] - e["hist"][0][1]
        dx = e["hist"][-1][2] - e["hist"][0][2]
        chave = None
        if abs(dd) >= DUAS_DIST and abs(dd) > abs(dx):
            chave = "duas_afastar" if dd > 0 else "duas_aproximar"
        elif abs(dx) >= DUAS_SWIPE:
            chave = "duas_swipe_direita" if dx > 0 else "duas_swipe_esquerda"
        if chave and agora - e["ult"] > 1.2:
            g = cad.por_pose.get(chave)
            if g:
                _executar_acao_unica(cad.acoes.get(g["acao_id"]))
            e["ult"], e["hist"] = agora, []
        e["rotulo"] = "DUAS MAOS"
        return True
    e["hist"] = []
    return False

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
    """Ações disparadas uma vez (ao segurar o gesto pelo tempo definido). Uma falha aqui não derruba o loop."""
    try:
        _acao_unica(acao)
    except Exception as e:
        print(f"\n[GESTOS]: a ação '{(acao or {}).get('nome', '?')}' falhou: {e!r}")


def _acao_unica(acao):
    if not acao:
        return
    tipo, comp = gl.tipo_efetivo(acao), acao.get("valor", "")
    if tipo == "macro":
        from ghost.automacao import macros
        if macros.em_execucao():
            return                                   # não empilha a mesma macro várias vezes
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
_geracao = 0      # cada "ativar gestos" cria uma geração; um loop antigo que ainda esteja saindo não continua


def loop_gestos(geracao):
    global camera_ativa
    nome_janela = "GHOST - Gestos"
    janela_aberta = False
    detector = None
    arrastando = False
    try:
        detector = gl.criar_detector_maos(num_maos=2)
        duas = {"zoom_ref": None, "hist": [], "ult": 0.0, "rotulo": ""}
        cad = Cadastro()
        camera.iniciar("gestos")

        cx, cy = user32.GetSystemMetrics(0) / 2, user32.GetSystemMetrics(1) / 2
        pausado = False
        pinca_ini, arrastando = None, False
        gesto_atual, gesto_desde, gesto_disparou = None, 0.0, False
        hist_pulso, ult_swipe = [], 0.0
        rolagem_y, acum_rolagem = None, 0.0
        ultimo_id, t0, ult_verif = 0, time.monotonic(), 0.0

        while camera_ativa and geracao == _geracao:
            ultimo_id, frame = camera.ler(ultimo_id, timeout=1.0)
            if frame is None:
                if arrastando:                       # sem imagem no meio de um arrasto: solta o botão
                    _mouse(ESQ_UP)
                    arrastando, pinca_ini = False, None
                if camera.erro and "gestos" in camera.em_uso():
                    _avisar(f"Senhor, {camera.erro}.")
                    break
                time.sleep(0.2)                      # câmera suspensa (cadastro aberto): não gira a CPU à toa
                continue
            if macros_rodando():                     # durante uma macro, o gesto não mexe no mouse
                continue
            frame = frame.copy()
            agora = time.monotonic()
            if agora - ult_verif > 2:
                cad.verificar(); ult_verif = agora

            maos = gl.detectar_maos(detector, frame, (agora - t0) * 1000)
            em_duas = len(maos) == 2 and not pausado and _processar_duas_maos(maos, cad, agora, duas)
            if em_duas or not maos:
                p = None
            elif len(maos) == 2:
                p = maos[1] if MAO_PRINCIPAL == "direita" else maos[0]
            else:
                p = maos[0]
            rotulo = duas["rotulo"] if em_duas else "sem mão"
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

            else:
                gesto_atual = None
                if arrastando:
                    _mouse(ESQ_UP); arrastando = False
                pinca_ini, rolagem_y, hist_pulso = None, None, []

            if MOSTRAR_JANELA:
                for m in maos:
                    gl.desenhar_mao(frame, m)
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
        if detector is not None:
            try:
                detector.close()                     # libera o grafo nativo do MediaPipe
            except Exception:
                pass
        if janela_aberta:
            try:
                cv2.destroyWindow(nome_janela); cv2.waitKey(1)
            except Exception:
                pass
        if geracao == _geracao:                      # só o loop atual mexe no estado global
            camera.parar("gestos")
            camera_ativa = False


def macros_rodando():
    try:
        from ghost.automacao import macros
        return macros.em_execucao()
    except Exception:
        return False

def alternar_camera(ligar=True, falar_callback=None, executar_comando=None):
    """Chamada pelos comandos de voz do automacoes.py."""
    global camera_ativa, _falar, _executar_comando
    _falar = falar_callback
    if executar_comando:
        _executar_comando = executar_comando
    global _geracao
    if ligar and not camera_ativa:
        camera_ativa = True
        _geracao += 1
        threading.Thread(target=loop_gestos, args=(_geracao,), daemon=True, name="gestos").start()
        if falar_callback:
            falar_callback("Controle por gestos ativado, senhor.")
    elif not ligar and camera_ativa:
        camera_ativa = False
        _geracao += 1
        if falar_callback:
            falar_callback("Controle por gestos desativado, senhor.")
    elif ligar and falar_callback:
        falar_callback("O controle por gestos já está ativo, senhor.")
