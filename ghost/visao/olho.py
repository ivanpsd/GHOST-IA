"""
GHOST - Enxergar as janelas: achar, focar, fotografar e ler o texto (OCR do próprio Windows, sem internet).

Usado pelas skills gravadas por demonstração: na gravação, guarda o texto em volta de cada clique
(ex.: o botão "Incluir"); na execução, procura esse texto de novo na janela para clicar no lugar certo,
mesmo que a janela tenha mudado de tamanho ou de posição.

- capturar(hwnd): foto da janela mesmo que esteja atrás de outra (PrintWindow).
- ler(imagem): palavras com posição, pelo OCR do Windows em pt-BR (~0,5 s por janela).
- achar_texto(palavras, alvo): onde está um texto ("Incluir", "Outras Ações") na foto.
- achar_imagem(foto, recorte): onde está um pedaço de imagem (quando não há texto para procurar).
As funções de busca são puras (testáveis em qualquer sistema); as de janela/OCR só no Windows.
"""
import asyncio
import ctypes
import io
import os
import re
import unicodedata


# =============================================================
# 1. FUNÇÕES PURAS (texto e imagem)
# =============================================================
def normalizar(texto):
    t = unicodedata.normalize("NFD", (texto or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", t)).strip()


def _caixa(palavras):
    x1 = min(p["x"] for p in palavras)
    y1 = min(p["y"] for p in palavras)
    x2 = max(p["x"] + p["w"] for p in palavras)
    y2 = max(p["y"] + p["h"] for p in palavras)
    return {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1}


def _centro(c):
    return c["x"] + c["w"] / 2, c["y"] + c["h"] / 2


def achar_texto(palavras, alvo, perto=None):
    """Caixas onde o texto `alvo` aparece (uma ou mais palavras seguidas na mesma linha).
    palavras: [{"texto","x","y","w","h","linha"}]. perto=(x, y): ordena pela distância a esse ponto."""
    alvo_n = normalizar(alvo).split()
    if not alvo_n:
        return []
    achados = []
    for i in range(len(palavras)):
        trecho = palavras[i:i + len(alvo_n)]
        if len(trecho) < len(alvo_n) or len({p["linha"] for p in trecho}) > 1:
            continue
        if [normalizar(p["texto"]) for p in trecho] == alvo_n:
            achados.append(_caixa(trecho))
    if not achados and len(alvo_n) == 1:          # OCR grudou símbolo na palavra ("•Incluir", "+Incluir")
        for p in palavras:
            if alvo_n[0] in normalizar(p["texto"]).split() or normalizar(p["texto"]).endswith(alvo_n[0]):
                achados.append(_caixa([p]))
    if not achados:                               # OCR errou uma letra ("Manutatura"): aceita texto bem parecido
        import difflib
        alvo_s = " ".join(alvo_n)
        for i in range(len(palavras)):
            for tam in {max(1, len(alvo_n) - 1), len(alvo_n), len(alvo_n) + 1}:
                trecho = palavras[i:i + tam]
                if len(trecho) < tam or len({p["linha"] for p in trecho}) > 1:
                    continue
                if difflib.SequenceMatcher(None, " ".join(normalizar(p["texto"]) for p in trecho), alvo_s).ratio() >= 0.86:
                    achados.append(_caixa(trecho))
    if perto:
        achados.sort(key=lambda c: (_centro(c)[0] - perto[0]) ** 2 + (_centro(c)[1] - perto[1]) ** 2)
    return achados


def ancora_do_clique(palavras, x, y, raio=60):
    """Texto que identifica o ponto clicado: a linha de texto em cima do clique; senão a mais próxima
    (até `raio` px), dando preferência ao rótulo à esquerda ou acima (campo vazio ao lado de "Cliente").
    Devolve {"texto", "dx", "dy"} (deslocamento do clique em relação ao centro do texto) ou None."""
    linhas = {}
    for p in palavras:
        linhas.setdefault(p["linha"], []).append(p)
    candidatos = []
    for ps in linhas.values():
        # divide a linha em blocos (o OCR junta na mesma "linha" botões distantes: "Incluir   Alterar")
        ps = sorted(ps, key=lambda p: p["x"])
        bloco = [ps[0]]
        blocos = []
        for p in ps[1:]:
            ant = bloco[-1]
            if p["x"] - (ant["x"] + ant["w"]) > max(25, ant["h"] * 1.6):
                blocos.append(bloco)
                bloco = [p]
            else:
                bloco.append(p)
        blocos.append(bloco)
        for b in blocos:
            c = _caixa(b)
            texto = " ".join(p["texto"] for p in b).strip(" •·+-*>")
            if not re.search(r"\w", texto):
                continue
            dentro = c["x"] - 4 <= x <= c["x"] + c["w"] + 4 and c["y"] - 6 <= y <= c["y"] + c["h"] + 6
            cx, cy = _centro(c)
            dist = 0 if dentro else max(0, abs(x - cx) - c["w"] / 2) + max(0, abs(y - cy) - c["h"] / 2)
            if not dentro and cx > x and abs(cy - y) > c["h"]:
                dist *= 1.5                          # rótulo abaixo/à direita: menos provável
            candidatos.append((dist, -len(texto), texto, c))
    if not candidatos:
        return None
    dist, _, texto, c = min(candidatos)
    if dist > raio:
        return None
    if len(texto) > 40:                              # parágrafo inteiro: pega só as palavras do clique
        texto = " ".join(texto.split()[:5])
    cx, cy = _centro(c)
    return {"texto": texto, "dx": round(x - cx), "dy": round(y - cy)}


def achar_imagem(foto, recorte, limite=0.85):
    """(x, y) do centro do recorte dentro da foto (PIL.Image), ou None. Usa OpenCV."""
    import cv2
    import numpy as np
    f = cv2.cvtColor(np.asarray(foto.convert("RGB")), cv2.COLOR_RGB2GRAY)
    r = cv2.cvtColor(np.asarray(recorte.convert("RGB")), cv2.COLOR_RGB2GRAY)
    if r.shape[0] > f.shape[0] or r.shape[1] > f.shape[1]:
        return None
    res = cv2.matchTemplate(f, r, cv2.TM_CCOEFF_NORMED)
    _, melhor, _, pos = cv2.minMaxLoc(res)
    if melhor < limite:
        return None
    return pos[0] + r.shape[1] // 2, pos[1] + r.shape[0] // 2


# =============================================================
# 2. JANELAS DO WINDOWS
# =============================================================
def _wt():
    import ctypes.wintypes as wt
    return wt


def info_janela(hwnd):
    """{"hwnd","titulo","exe","rect":(x,y,w,h),"classe"} da janela de nível superior."""
    wt = _wt()
    user32 = ctypes.windll.user32
    hwnd = user32.GetAncestor(hwnd, 2) or hwnd            # GA_ROOT
    n = user32.GetWindowTextLengthW(hwnd)
    titulo = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, titulo, n + 1)
    classe = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, classe, 256)
    r = wt.RECT()
    if ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:
        user32.GetWindowRect(hwnd, ctypes.byref(r))
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    exe = ""
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid.value)
    if h:
        buf = ctypes.create_unicode_buffer(520)
        tam = wt.DWORD(520)
        if ctypes.windll.kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(tam)):
            exe = os.path.basename(buf.value).lower()
        ctypes.windll.kernel32.CloseHandle(h)
    return {"hwnd": hwnd, "titulo": titulo.value, "exe": exe, "classe": classe.value,
            "rect": (r.left, r.top, r.right - r.left, r.bottom - r.top)}


def janela_no_ponto(x, y):
    wt = _wt()
    return info_janela(ctypes.windll.user32.WindowFromPoint(wt.POINT(int(x), int(y))))


def janela_em_foco():
    return info_janela(ctypes.windll.user32.GetForegroundWindow())


def nome_base(titulo):
    """'TOTVS Webapp - TOTVS Manufatura (TOTVS) 02.9.0005' -> 'TOTVS Webapp'; 'Pasta1 - Excel' -> 'Excel'."""
    partes = [p.strip() for p in re.split(r"\s+[-–—]\s+", titulo or "") if p.strip()]
    if not partes:
        return ""
    # programas que põem o nome do arquivo antes ("Pasta1 - Excel", "doc - Google Chrome"): o nome do app vem por último
    conhecidos = ("excel", "word", "google chrome", "microsoft edge", "bloco de notas", "notepad", "outlook")
    if normalizar(partes[-1]) in conhecidos:
        return partes[-1]
    return partes[0]


def listar_janelas():
    wt = _wt()
    user32 = ctypes.windll.user32
    achadas = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(h, _):
        if user32.IsWindowVisible(h) and user32.GetWindowTextLengthW(h):
            achadas.append(h)
        return True
    user32.EnumWindows(cb, 0)
    return [info_janela(h) for h in achadas]


def achar_janela(exe, titulo_base):
    """Janela do mesmo programa com o mesmo nome base (a parte variável do título pode mudar)."""
    alvo = normalizar(titulo_base)
    candidatas = [j for j in listar_janelas() if (not exe or j["exe"] == exe)]
    for j in candidatas:
        if normalizar(nome_base(j["titulo"])) == alvo:
            return j
    for j in candidatas:
        if alvo and alvo in normalizar(j["titulo"]):
            return j
    return None


def focar(hwnd):
    user32 = ctypes.windll.user32
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)                          # SW_RESTORE
    user32.keybd_event(0x12, 0, 0, 0)                      # Alt solto: o Windows deixa trocar o foco
    user32.keybd_event(0x12, 0, 2, 0)
    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)


# =============================================================
# 3. FOTO E OCR
# =============================================================
def capturar(hwnd):
    """PIL.Image da janela (funciona mesmo atrás de outras; minimizada não dá)."""
    from PIL import Image
    wt = _wt()
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    if w <= 0 or h <= 0:
        raise RuntimeError("janela sem tamanho (minimizada?)")
    dc = user32.GetWindowDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(dc)
    bmp = gdi32.CreateCompatibleBitmap(dc, w, h)
    gdi32.SelectObject(mdc, bmp)
    try:
        user32.PrintWindow(hwnd, mdc, 2)                   # PW_RENDERFULLCONTENT: Chrome/Edge também

        class BMI(ctypes.Structure):
            _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32), ("biHeight", ctypes.c_int32),
                        ("biPlanes", ctypes.c_uint16), ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                        ("biSizeImage", ctypes.c_uint32), ("x", ctypes.c_int32), ("y", ctypes.c_int32),
                        ("u", ctypes.c_uint32), ("i", ctypes.c_uint32)]
        bmi = BMI(biSize=ctypes.sizeof(BMI), biWidth=w, biHeight=-h, biPlanes=1, biBitCount=32)
        buf = ctypes.create_string_buffer(w * h * 4)
        gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bmi), 0)
    finally:
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mdc)
        user32.ReleaseDC(hwnd, dc)
    # a área da janela pela DWM (sem a sombra) pode ser menor que o GetWindowRect: guarda o deslocamento
    img = Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1).copy()
    img.info["origem"] = (r.left, r.top)
    return img


def capturar_tela():
    """Foto de todos os monitores (para listas que abrem fora da janela). info['origem'] = canto da área virtual."""
    from PIL import ImageGrab
    user32 = ctypes.windll.user32
    img = ImageGrab.grab(all_screens=True)
    img.info["origem"] = (user32.GetSystemMetrics(76), user32.GetSystemMetrics(77))   # SM_X/YVIRTUALSCREEN
    return img


def monitores():
    """Retângulos (x1, y1, x2, y2) dos monitores: o principal é o 1; os outros da esquerda para a direita."""
    wt = _wt()
    lista = []

    class _Info(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]

    def cb(hmon, _hdc, _rect, _dado):
        info = _Info()
        info.cbSize = ctypes.sizeof(_Info)
        ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(info))
        r = info.rcMonitor
        lista.append(((r.left, r.top, r.right, r.bottom), bool(info.dwFlags & 1)))
        return True

    tipo = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(wt.RECT), ctypes.c_void_p)
    ctypes.windll.user32.EnumDisplayMonitors(None, None, tipo(cb), None)
    lista.sort(key=lambda m: (not m[1], m[0][0]))
    return [m[0] for m in lista]


def capturar_monitor(n):
    """Foto do monitor n (1 = principal). None se não existir."""
    from PIL import ImageGrab
    mons = monitores()
    if not 1 <= n <= len(mons):
        return None
    return ImageGrab.grab(bbox=mons[n - 1], all_screens=True)


async def _ocr_async(img):
    from winrt.windows.globalization import Language
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream
    png = io.BytesIO()
    img.save(png, "PNG")
    fluxo = InMemoryRandomAccessStream()
    escritor = DataWriter(fluxo)
    escritor.write_bytes(png.getvalue())
    await escritor.store_async()
    fluxo.seek(0)
    bitmap = await (await BitmapDecoder.create_async(fluxo)).get_software_bitmap_async()
    motor = OcrEngine.try_create_from_language(Language("pt-BR")) or OcrEngine.try_create_from_user_profile_languages()
    return await motor.recognize_async(bitmap)


def ler(img):
    """Palavras da imagem: [{"texto","x","y","w","h","linha"}] em pixels da imagem."""
    escala = 1
    if img.width < 1200:                                  # texto pequeno: o OCR acerta mais com a imagem maior
        escala = 2
        img = img.resize((img.width * 2, img.height * 2))
    res = asyncio.run(_ocr_async(img))
    palavras = []
    for i, linha in enumerate(res.lines):
        for p in linha.words:
            r = p.bounding_rect
            palavras.append({"texto": p.text, "x": r.x / escala, "y": r.y / escala, "w": r.width / escala,
                             "h": r.height / escala, "linha": i})
    return palavras
