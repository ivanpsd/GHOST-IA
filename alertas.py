"""
GHOST - Alertas proativos: ele avisa sozinho, sem você perguntar.

| Alerta              | Quando                                                     | Repete no máximo |
|---------------------|------------------------------------------------------------|------------------|
| Disco quase cheio   | C: com menos de 10% ou 15 GB livres                        | 1x por dia       |
| PC sobrecarregado   | memória acima de 92% por 3 checagens seguidas              | a cada 2 h       |
| Bateria fraca       | abaixo de 20% e fora da tomada                             | a cada 30 min    |
| Internet            | caiu (e quando voltou)                                     | a cada queda     |
| Pausa               | 90 min seguidos usando o PC sem parar 5 min                | a cada 90 min    |
| Chuva na saída      | perto do fim do expediente, se for chover na hora de sair  | 1x por dia       |

Respeita: horário (8h–20h, exceto bateria/internet), você estar falando com ele,
e "Ghost, silenciar alertas por 1 hora" / "pausar alertas" / "retomar alertas".
Os limites estão nas constantes abaixo.
"""
import time
import socket
import ctypes
import threading
from datetime import datetime, timedelta

INTERVALO = 120                 # segundos entre checagens
HORARIO = (8, 20)
DISCO_MIN_PCT, DISCO_MIN_GB = 10, 15
MEMORIA_MAX_PCT = 92
BATERIA_MIN_PCT = 20
PAUSA_APOS_MIN = 90
PARADO_CONTA_COMO_PAUSA_MIN = 5
HORA_SAIDA = "18:00"            # chuva: avisa ~1h30 antes
CHUVA_MIN_PCT = 60

_falar = _ocupado = None
_ultimo = {}                    # tipo -> momento do último aviso
_silencio_ate = 0.0
ativo = True
_estado = {"memoria_alta": 0, "internet": True, "uso_desde": time.time()}


# ---------------- leituras do Windows (ctypes, sem programas extras)
def _disco_c():
    livre, total, _ = ctypes.c_ulonglong(), ctypes.c_ulonglong(), ctypes.c_ulonglong()
    ctypes.windll.kernel32.GetDiskFreeSpaceExW("C:\\", ctypes.byref(livre), ctypes.byref(total), ctypes.byref(_))
    return livre.value / 1024 ** 3, 100 * livre.value / max(total.value, 1)


def _memoria_pct():
    class MS(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong)] + \
                   [(n, ctypes.c_ulonglong) for n in ("t", "a", "tp", "ap", "tv", "av", "ae")]
    m = MS(); m.dwLength = ctypes.sizeof(MS)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.dwMemoryLoad


def _bateria():
    class SPS(ctypes.Structure):
        _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                    ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                    ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]
    s = SPS(); ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s))
    if s.BatteryFlag == 128 or s.BatteryLifePercent == 255:
        return None, True  # sem bateria
    return s.BatteryLifePercent, s.ACLineStatus == 1


def _segundos_parado():
    class LII(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
    li = LII(); li.cbSize = ctypes.sizeof(li)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li))
    return (ctypes.windll.kernel32.GetTickCount() - li.dwTime) / 1000.0


def _internet():
    for host in (("1.1.1.1", 53), ("8.8.8.8", 53)):
        try:
            socket.create_connection(host, timeout=2).close()
            return True
        except OSError:
            continue
    return False


# ---------------- regras
def _pode(tipo, intervalo_s):
    return time.time() - _ultimo.get(tipo, 0) >= intervalo_s


def _avisar(tipo, frase):
    _ultimo[tipo] = time.time()
    print(f"\n[ALERTA]: {frase}")
    if _falar:
        _falar(frase)


def _chuva_na_saida():
    import requests, preferencias, resumo
    cidade = preferencias.carregar().get("cidade", "Santana de Parnaíba")
    lat, lon = resumo._coordenadas(cidade)
    w = requests.get("https://api.open-meteo.com/v1/forecast", timeout=8, params={
        "latitude": lat, "longitude": lon, "hourly": "precipitation_probability",
        "timezone": "America/Sao_Paulo", "forecast_days": 1}).json()
    saida = int(HORA_SAIDA.split(":")[0])
    horas = w["hourly"]["time"]; prob = w["hourly"]["precipitation_probability"]
    janela = [p for t, p in zip(horas, prob) if saida - 1 <= int(t[11:13]) <= saida + 1 and p is not None]
    return max(janela) if janela else 0


def checar():
    agora = datetime.now()
    no_horario = HORARIO[0] <= agora.hour < HORARIO[1]
    dia_util = agora.weekday() < 5

    # internet (vale sempre)
    on = _internet()
    if on != _estado["internet"]:
        _estado["internet"] = on
        _avisar("internet", "Senhor, a internet voltou." if on else
                "Senhor, a conexão com a internet caiu. Vou funcionar só com o que é local até voltar.")

    # bateria (vale sempre)
    pct, na_tomada = _bateria()
    if pct is not None and pct < BATERIA_MIN_PCT and not na_tomada and _pode("bateria", 1800):
        _avisar("bateria", f"Senhor, a bateria está em {pct} por cento e o notebook está fora da tomada.")

    if not no_horario:
        return

    livre_gb, livre_pct = _disco_c()
    if (livre_pct < DISCO_MIN_PCT or livre_gb < DISCO_MIN_GB) and _pode("disco", 86400):
        _avisar("disco", f"Senhor, o disco C está quase cheio: restam {livre_gb:.0f} gigas. "
                         "Quer que eu abra a limpeza de disco?")

    mem = _memoria_pct()
    _estado["memoria_alta"] = _estado["memoria_alta"] + 1 if mem >= MEMORIA_MAX_PCT else 0
    if _estado["memoria_alta"] >= 3 and _pode("memoria", 7200):
        _avisar("memoria", f"Senhor, a memória do computador está em {mem} por cento há alguns minutos; "
                           "isso deixa tudo lento. Fechar programas parados deve ajudar.")

    # pausa: tempo contínuo de uso
    if _segundos_parado() > PARADO_CONTA_COMO_PAUSA_MIN * 60:
        _estado["uso_desde"] = time.time()
    elif time.time() - _estado["uso_desde"] > PAUSA_APOS_MIN * 60 and _pode("pausa", PAUSA_APOS_MIN * 60):
        _estado["uso_desde"] = time.time()
        _avisar("pausa", "Senhor, já faz uma hora e meia sem pausa. Que tal levantar e tomar uma água?")

    # chuva na hora da saída (dias úteis, ~1h30 antes)
    h, m = map(int, HORA_SAIDA.split(":"))
    saida = agora.replace(hour=h, minute=m, second=0, microsecond=0)
    if dia_util and timedelta(0) < saida - agora <= timedelta(minutes=90) and _pode("chuva", 43200):
        try:
            p = _chuva_na_saida()
            _ultimo["chuva"] = time.time()  # checa só uma vez por tarde, chova ou não
            if p >= CHUVA_MIN_PCT:
                _avisar("chuva", f"Senhor, há {p} por cento de chance de chuva perto da hora da saída. "
                                 "Leve o guarda-chuva.")
        except Exception as e:
            print(f"\n[ALERTA]: previsão indisponível ({e})")


def _loop():
    while True:
        time.sleep(INTERVALO)
        try:
            if ativo and time.time() >= _silencio_ate and not (_ocupado and _ocupado()):
                checar()
        except Exception as e:
            print(f"\n[ALERTA]: erro: {e!r}")


def iniciar(falar, ocupado):
    global _falar, _ocupado
    _falar, _ocupado = falar, ocupado
    _estado["internet"] = _internet()
    threading.Thread(target=_loop, daemon=True).start()


def silenciar(minutos, falar=None):
    global _silencio_ate
    _silencio_ate = time.time() + minutos * 60
    if falar:
        falar(f"Alertas em silêncio por {minutos} minutos, senhor.")


def ligar(on, falar=None):
    global ativo, _silencio_ate
    ativo, _silencio_ate = on, 0.0
    if falar:
        falar("Alertas retomados, senhor." if on else "Alertas pausados, senhor.")


def situacao():
    """Resumo do estado do PC agora (para 'como está o computador?')."""
    livre_gb, livre_pct = _disco_c()
    pct, na_tomada = _bateria()
    bat = "" if pct is None else f", bateria em {pct} por cento{' na tomada' if na_tomada else ''}"
    return (f"Disco C com {livre_gb:.0f} gigas livres, memória em {_memoria_pct()} por cento{bat}, "
            f"internet {'ok' if _internet() else 'fora do ar'}.")
