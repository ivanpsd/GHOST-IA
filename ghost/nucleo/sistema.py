"""
GHOST - Leituras do Windows usadas por vários módulos (um só lugar, sem repetir código).
"""
import ctypes
import socket
import threading
import time

# Testar a internet pela porta 443 (HTTPS), nos serviços que o Ghost usa de verdade.
# (Antes era a porta 53 de DNS público, que redes de empresa costumam bloquear mesmo com internet.)
HOSTS_INTERNET = (("api.groq.com", 443), ("www.google.com", 443), ("1.1.1.1", 443))

_cache_net = {"t": 0.0, "on": True}
_trava_net = threading.Lock()


def internet(timeout=1.5, cache_s=0.0):
    """True se algum serviço da internet responde. cache_s > 0 reaproveita o último resultado."""
    with _trava_net:
        if cache_s and time.time() - _cache_net["t"] < cache_s:
            return _cache_net["on"]
    on = False
    for host in HOSTS_INTERNET:
        try:
            socket.create_connection(host, timeout=timeout).close()
            on = True
            break
        except OSError:
            continue
    with _trava_net:
        _cache_net.update(t=time.time(), on=on)
    return on


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def segundos_ocioso():
    """Há quantos segundos não se usa teclado/mouse.
    GetTickCount devolve um número de 32 bits SEM sinal: lido como 'int' (padrão do ctypes) ficava
    negativo depois de ~25 dias com o PC ligado e o tempo ocioso saía errado."""
    try:
        k32, u32 = ctypes.windll.kernel32, ctypes.windll.user32
    except AttributeError:          # fora do Windows (testes)
        return 0.0
    k32.GetTickCount.restype = ctypes.c_uint32
    li = _LASTINPUTINFO()
    li.cbSize = ctypes.sizeof(li)
    if not u32.GetLastInputInfo(ctypes.byref(li)):
        return 0.0
    return ((k32.GetTickCount() - li.dwTime) & 0xFFFFFFFF) / 1000.0


class _Memoria(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong), ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t), ("PrivateUsage", ctypes.c_size_t)]


def memoria_ghost_mb():
    """(memória em uso agora, memória reservada) do próprio Ghost, em MB. (None, None) fora do Windows."""
    try:
        k32 = ctypes.WinDLL("kernel32")
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.K32GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
        m = _Memoria()
        m.cb = ctypes.sizeof(m)
        if k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(m), m.cb):
            return round(m.WorkingSetSize / 2**20), round(m.PrivateUsage / 2**20)
    except Exception:
        pass
    return None, None


def configurar_dpi():
    """Coordenadas reais de tela em todos os monitores (escalas diferentes). Chamar uma vez, no início."""
    try:
        u32 = ctypes.windll.user32
    except AttributeError:
        return
    try:
        u32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))      # por monitor, v2
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            u32.SetProcessDPIAware()
        except Exception:
            pass
