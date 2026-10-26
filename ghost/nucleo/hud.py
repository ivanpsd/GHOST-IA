"""
GHOST - Painel visual (HUD) no topo da tela.

Uma faixa discreta, sempre visível e "atravessável" (o clique passa para a
janela de baixo), que mostra o que o Ghost está fazendo:
  ● cinza-quente  em espera (ouvindo só a palavra "Ghost")
  ● ouro          ouvindo você
  ● brasa         entendendo / pensando
  ● laranja claro falando (mostra a frase)
  ● vermelho      erro
A tela completa de indicadores é o painel (ghost/nucleo/painel.py): "Ghost, abrir painel".
Fica quase transparente quando está em espera.
Por voz: "Ghost, esconder faixa" / "Ghost, mostrar faixa".
"""
import ctypes
import queue
import threading
import time

LARGURA, ALTURA = 560, 58
TRANSPARENCIA_ATIVO = 0.92
TRANSPARENCIA_ESPERA = 0.35
VOLTA_A_ESPERA_S = 6        # segundos sem novidade até voltar ao modo espera

# mesma paleta da tela de indicadores (brasa e ouro)
CORES = {"espera": "#9a8770", "ouvindo": "#e8b04b", "pensando": "#ff8a3a", "falando": "#ffb35c", "erro": "#e0503a",
         "conversa": "#f0c46a", "dormindo": "#5b4a3a"}
ROTULOS = {"espera": "GHOST · em espera", "ouvindo": "GHOST · ouvindo", "pensando": "GHOST · pensando",
           "falando": "GHOST · falando", "erro": "GHOST · erro", "conversa": "GHOST · conversa ativa",
           "dormindo": "GHOST · dormindo"}
DISCRETOS = ("espera", "dormindo")     # estados com o painel quase transparente
FUNDO, TEXTO, TEXTO_FRACO = "#120d09", "#e9dcc6", "#9a8770"

_fila = queue.Queue()
_repouso = ["espera", ""]    # para onde o painel volta quando nada acontece (muda com a conversa / dormindo)
_visivel = True
_iniciado = False


def _cortar(t, n=78):
    t = " ".join((t or "").split())
    return t if len(t) <= n else t[: n - 1] + "…"


# ---------- API usada pelo resto do Ghost (pode ser chamada de qualquer thread)
def estado(nome, texto=""):
    _fila.put(("estado", nome, texto))
    try:
        from ghost.nucleo import painel
        painel.estado(nome, texto)          # a tela de indicadores mostra o mesmo estado
    except Exception:
        pass

def ouvindo(texto="Pode falar…"):
    estado("ouvindo", texto)

def pensando(texto=""):
    estado("pensando", texto)

def falando(texto=""):
    estado("falando", texto)

def espera():
    estado(*_repouso)


def repouso(nome="espera", texto=""):
    """Define o estado de descanso do painel (espera normal, conversa ativa ou dormindo) e já mostra."""
    _repouso[:] = [nome, texto]
    estado(nome, texto)

def erro(texto):
    estado("erro", texto)

def mostrar(on=True):
    _fila.put(("mostrar", on, ""))


# ---------- janela (thread própria do Tkinter)
def _atravessavel(janela):
    """Clique passa através da janela; ela não rouba o foco nem aparece no Alt+Tab."""
    try:
        hwnd = ctypes.windll.user32.GetParent(janela.winfo_id())
        GWL_EXSTYLE = -20
        estilo = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        estilo |= 0x80000 | 0x20 | 0x80 | 0x08000000   # LAYERED | TRANSPARENT | TOOLWINDOW | NOACTIVATE
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, estilo)
    except Exception:
        pass


def _rodar():
    import tkinter as tk
    raiz = tk.Tk()
    raiz.overrideredirect(True)
    raiz.attributes("-topmost", True)
    raiz.attributes("-alpha", TRANSPARENCIA_ESPERA)
    raiz.configure(bg=FUNDO)
    largura_tela = raiz.winfo_screenwidth()
    raiz.geometry(f"{LARGURA}x{ALTURA}+{(largura_tela - LARGURA) // 2}+8")

    tela = tk.Canvas(raiz, width=LARGURA, height=ALTURA, bg=FUNDO, highlightthickness=0)
    tela.pack()
    borda = tela.create_rectangle(1, 1, LARGURA - 2, ALTURA - 2, outline=CORES["espera"], width=1)
    ponto = tela.create_oval(16, 21, 32, 37, fill=CORES["espera"], outline="")
    titulo = tela.create_text(44, 17, anchor="w", text=ROTULOS["espera"], fill=TEXTO_FRACO,
                              font=("Segoe UI Semibold", 9))
    linha = tela.create_text(44, 37, anchor="w", text="Diga \"Ghost\" ou segure F9", fill=TEXTO,
                             font=("Segoe UI", 11))
    raiz.update_idletasks()
    _atravessavel(raiz)

    st = {"nome": "espera", "desde": time.time(), "pulso": 0}

    def aplicar(nome, texto):
        cor = CORES.get(nome, CORES["espera"])
        st["nome"], st["desde"] = nome, time.time()
        tela.itemconfig(ponto, fill=cor)
        tela.itemconfig(borda, outline=cor)
        tela.itemconfig(titulo, text=ROTULOS.get(nome, "GHOST"))
        tela.itemconfig(linha, text=_cortar(texto) if texto else
                        ("Diga \"Ghost\" ou segure F9" if nome == "espera" else ""))
        raiz.attributes("-alpha", TRANSPARENCIA_ESPERA if nome in DISCRETOS else TRANSPARENCIA_ATIVO)

    def ciclo():
        try:
            _ciclo_corpo()
        except Exception as e:                 # um erro aqui não pode congelar o painel para sempre
            print(f"\n[PAINEL]: {e!r}")
        finally:
            raiz.after(80, ciclo)

    def _ciclo_corpo():
        try:
            while True:
                tipo, a, b = _fila.get_nowait()
                if tipo == "estado":
                    aplicar(a, b)
                elif tipo == "mostrar":
                    raiz.deiconify() if a else raiz.withdraw()
        except queue.Empty:
            pass
        # volta para a espera depois de um tempo sem novidade (exceto enquanto ouve)
        if st["nome"] in ("falando", "erro", "pensando") and time.time() - st["desde"] > VOLTA_A_ESPERA_S:
            aplicar(*_repouso)
        # pulso do ponto enquanto ouve/pensa
        if st["nome"] in ("ouvindo", "pensando", "conversa"):
            st["pulso"] = (st["pulso"] + 1) % 10
            r = 8 + (2 if st["pulso"] < 5 else 0)
            tela.coords(ponto, 24 - r, 29 - r, 24 + r, 29 + r)
        else:
            tela.coords(ponto, 16, 21, 32, 37)
        st["topo"] = st.get("topo", 0) + 1
        if st["topo"] % 25 == 0:               # reafirma "sempre por cima" a cada ~2 s (não 12x por segundo)
            raiz.attributes("-topmost", True)

    ciclo()
    raiz.mainloop()


def iniciar(mostrar_ao_iniciar=True):
    global _iniciado
    if _iniciado:
        return
    _iniciado = True
    threading.Thread(target=_rodar, daemon=True).start()
    if not mostrar_ao_iniciar:
        mostrar(False)
