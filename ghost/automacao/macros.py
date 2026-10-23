"""
GHOST - Gravação e execução de macros (ações gravadas).

Gravar: tudo o que você faz no teclado e com cliques/rolagem do mouse vira
uma lista de passos, com o tempo entre eles. Pressione F10 para terminar.
Executar: repete os passos no mesmo ritmo (ou mais rápido). Uma macro por vez;
Esc interrompe a execução. Teclas e botões do mouse nunca ficam presos.
"""
import threading
import time

from pynput import keyboard as kb
from pynput import mouse as ms

from ghost.nucleo import sistema

sistema.configurar_dpi()   # mesmas coordenadas na gravação e na execução, em todos os monitores

TECLA_PARAR = kb.Key.f10
TECLA_ABORTAR = kb.Key.esc       # durante a execução: interrompe a macro
PAUSA_MINIMA = 0.03    # segundos entre passos no modo rápido
MAX_ESPERA = 3.0       # no ritmo original, esperas maiores que isso são encurtadas

_executando = threading.Lock()
_abortar = threading.Event()


def em_execucao():
    return _executando.locked()


def abortar():
    _abortar.set()


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
    """Remove teclas/botões soltos sem o 'apertar' correspondente (ex.: o Enter que fechou a mensagem)
    e solta no fim o que ficou apertado (gravação encerrada no meio de um arrasto)."""
    apertadas, botoes, saida = set(), set(), []
    for p in passos:
        if p["tipo"] == "tecla":
            if p["pressionado"]:
                apertadas.add(p["vk"])
            elif p["vk"] not in apertadas:
                continue
            else:
                apertadas.discard(p["vk"])
        elif p["tipo"] == "mouse":
            if p["pressionado"]:
                botoes.add(p["botao"])
            elif p["botao"] not in botoes:
                continue
            else:
                botoes.discard(p["botao"])
        saida.append(p)
    t_fim = saida[-1]["t"] if saida else 0
    for b in botoes:
        x, y = next((q["x"], q["y"]) for q in reversed(saida) if q["tipo"] in ("mouse", "rolar"))
        saida.append({"tipo": "mouse", "x": x, "y": y, "botao": b, "pressionado": False, "t": t_fim})
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
    """Repete a macro. ritmo: 'original' (mesmo tempo, esperas longas encurtadas) ou 'rapido'.
    Se outra macro já estiver rodando, esta é ignorada (não entrelaça teclas e cliques)."""
    if not _executando.acquire(blocking=False):
        print("\n[MACRO]: outra macro já está rodando; ignorada.")
        return False
    _abortar.clear()
    ouvinte = kb.Listener(on_press=lambda k: _abortar.set() if k == TECLA_ABORTAR else None)
    ouvinte.start()
    try:
        _executar(passos, ritmo)
        return not _abortar.is_set()
    finally:
        ouvinte.stop()
        _executando.release()


def _executar(passos, ritmo):
    teclado, mouse = kb.Controller(), ms.Controller()
    anterior, apertadas, botoes = 0.0, [], set()
    try:
        for p in passos:
            espera = p["t"] - anterior
            anterior = p["t"]
            if _abortar.wait(PAUSA_MINIMA if ritmo == "rapido" else min(max(espera, 0), MAX_ESPERA)):
                print("\n[MACRO]: interrompida (Esc).")
                break
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
                if p["pressionado"]:
                    mouse.press(botao); botoes.add(botao)
                else:
                    mouse.release(botao); botoes.discard(botao)
            elif p["tipo"] == "rolar":
                mouse.position = (p["x"], p["y"])
                mouse.scroll(p["dx"], p["dy"])
    finally:
        for k in apertadas:  # nunca deixa tecla presa
            try:
                teclado.release(k)
            except Exception:
                pass
        for b in botoes:     # nem botão do mouse
            try:
                mouse.release(b)
            except Exception:
                pass
