"""
GHOST - Gravação e execução de macros (ações gravadas).

Gravar: tudo o que você faz no teclado e com cliques/rolagem do mouse vira
uma lista de passos, com o tempo entre eles. Pressione F10 para terminar.
Executar: repete os passos no mesmo ritmo (ou mais rápido).
"""
import time
import ctypes
import threading

from pynput import keyboard as kb, mouse as ms

try:
    ctypes.windll.user32.SetProcessDPIAware()  # mesmas coordenadas na gravação e na execução
except Exception:
    pass

TECLA_PARAR = kb.Key.f10
PAUSA_MINIMA = 0.03    # segundos entre passos no modo rápido
MAX_ESPERA = 3.0       # no ritmo original, esperas maiores que isso são encurtadas


def _info_tecla(k):
    vk = getattr(k, "vk", None)
    if vk is None and hasattr(k, "value"):
        vk = getattr(k.value, "vk", None)
    nome = getattr(k, "char", None) or getattr(k, "name", None) or str(k)
    return vk, nome


class Gravador:
    def __init__(self):
        self.passos = []
        self._t0 = None
        self._fim = threading.Event()
        self._teclas_ignoradas = set()

    def _add(self, passo):
        passo["t"] = round(time.monotonic() - self._t0, 3)
        self.passos.append(passo)

    # teclado
    def _down(self, k):
        if k == TECLA_PARAR:
            self._fim.set()
            return False
        vk, nome = _info_tecla(k)
        if vk is not None:
            self._add({"tipo": "tecla", "vk": vk, "nome": nome, "pressionado": True})

    def _up(self, k):
        if k == TECLA_PARAR:
            return False
        vk, nome = _info_tecla(k)
        if vk is not None:
            self._add({"tipo": "tecla", "vk": vk, "nome": nome, "pressionado": False})

    # mouse
    def _clique(self, x, y, botao, pressionado):
        self._add({"tipo": "mouse", "x": int(x), "y": int(y), "botao": botao.name, "pressionado": pressionado})

    def _rolar(self, x, y, dx, dy):
        self._add({"tipo": "rolar", "x": int(x), "y": int(y), "dx": dx, "dy": dy})

    def gravar(self, limite_segundos=300):
        """Bloqueia até F10 (ou o limite). Retorna a lista de passos."""
        self._t0 = time.monotonic()
        lt = kb.Listener(on_press=self._down, on_release=self._up)
        lm = ms.Listener(on_click=self._clique, on_scroll=self._rolar)
        lt.start(); lm.start()
        self._fim.wait(limite_segundos)
        lt.stop(); lm.stop()
        return _limpar(self.passos)


def _limpar(passos):
    """Remove teclas soltas sem o 'apertar' correspondente (ex.: o Enter que fechou a mensagem)."""
    apertadas, saida = set(), []
    for p in passos:
        if p["tipo"] == "tecla":
            if p["pressionado"]:
                apertadas.add(p["vk"])
            elif p["vk"] not in apertadas:
                continue
            else:
                apertadas.discard(p["vk"])
        saida.append(p)
    if saida:  # o tempo começa no primeiro passo real
        t0 = saida[0]["t"]
        for p in saida:
            p["t"] = round(p["t"] - t0, 3)
    return saida


def resumo(passos):
    teclas = sum(1 for p in passos if p["tipo"] == "tecla" and p["pressionado"])
    cliques = sum(1 for p in passos if p["tipo"] == "mouse" and p["pressionado"])
    rolagens = sum(1 for p in passos if p["tipo"] == "rolar")
    dur = passos[-1]["t"] if passos else 0
    return f"{teclas} teclas, {cliques} cliques, {rolagens} rolagens, {dur:.1f} s"


def executar(passos, ritmo="original"):
    """Repete a macro. ritmo: 'original' (mesmo tempo, esperas longas encurtadas) ou 'rapido'."""
    teclado, mouse = kb.Controller(), ms.Controller()
    anterior, apertadas = 0.0, []
    try:
        for p in passos:
            espera = p["t"] - anterior
            anterior = p["t"]
            time.sleep(PAUSA_MINIMA if ritmo == "rapido" else min(max(espera, 0), MAX_ESPERA))
            if p["tipo"] == "tecla":
                k = kb.KeyCode.from_vk(p["vk"])
                if p["pressionado"]:
                    teclado.press(k); apertadas.append(k)
                else:
                    teclado.release(k)
                    if k in apertadas:
                        apertadas.remove(k)
            elif p["tipo"] == "mouse":
                mouse.position = (p["x"], p["y"])
                botao = getattr(ms.Button, p["botao"], ms.Button.left)
                (mouse.press if p["pressionado"] else mouse.release)(botao)
            elif p["tipo"] == "rolar":
                mouse.position = (p["x"], p["y"])
                mouse.scroll(p["dx"], p["dy"])
    finally:
        for k in apertadas:  # nunca deixa tecla presa
            try:
                teclado.release(k)
            except Exception:
                pass
