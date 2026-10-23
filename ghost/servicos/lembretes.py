"""
GHOST - Lembretes e alarmes.
"Me lembra às 15h de ligar para o fornecedor", "daqui a 20 minutos me avisa do forno",
"quais são meus lembretes?", "cancela o lembrete do fornecedor".
A IA converte a fala em data/hora (ela recebe o horário atual). Na hora certa,
o Ghost fala o lembrete e mostra um aviso na tela (fica visível mesmo se você
não estiver ouvindo). Lembretes perdidos com o PC desligado são avisados ao abrir.
Arquivo: dados/lembretes.json (fora do Git).
"""
import ctypes
import threading
import time
import uuid
from datetime import datetime, timedelta

from ghost.nucleo import arquivo, caminhos

ARQUIVO = caminhos.dado("lembretes.json")
FORMATO = "%Y-%m-%d %H:%M"
AVISAR_ATRASADOS_HORAS = 12

_trava = threading.Lock()
_falar = None


def _carregar():
    return arquivo.ler_json(ARQUIVO, []) or []


def _gravar(lista):
    arquivo.salvar_json(ARQUIVO, lista)


def _data(l):
    """Data do lembrete; None se o item estiver estragado (é ignorado, não trava os outros)."""
    try:
        return datetime.strptime(l["quando"], FORMATO)
    except (KeyError, TypeError, ValueError):
        return None


def _quando_falado(dt):
    hoje = datetime.now().date()
    dia = "hoje" if dt.date() == hoje else "amanhã" if dt.date() == hoje + timedelta(days=1) else dt.strftime("%d/%m")
    return f"{dia} às {dt.strftime('%H:%M')}"


def criar(quando, texto):
    """quando: 'AAAA-MM-DD HH:MM'. Retorna a frase de confirmação."""
    dt = datetime.strptime(quando.strip()[:16].replace("T", " "), FORMATO)
    if dt < datetime.now() - timedelta(minutes=1):
        return f"Senhor, esse horário já passou ({_quando_falado(dt)}). Diga um horário futuro."
    with _trava:
        lista = _carregar()
        lista.append({"id": uuid.uuid4().hex[:8], "quando": dt.strftime(FORMATO), "texto": texto.strip()})
        _gravar(lista)
    return f"Combinado, senhor. Vou lembrar {_quando_falado(dt)}: {texto.strip()}."


def listar():
    with _trava:
        lista = sorted((l for l in _carregar() if _data(l)), key=lambda x: x["quando"])
    if not lista:
        return "Não há lembretes marcados, senhor."
    itens = [f"{_quando_falado(_data(l))}, {l['texto']}" for l in lista[:8]]
    return "Lembretes, senhor: " + "; ".join(itens) + "."


def cancelar(trecho):
    alvo = (trecho or "").lower()
    with _trava:
        lista = _carregar()
        restantes = [l for l in lista if not (alvo and alvo in str(l.get("texto", "")).lower())]
        if len(restantes) != len(lista):
            _gravar(restantes)
    n = len(lista) - len(restantes)
    return f"{n} lembrete{'s' if n != 1 else ''} cancelado{'s' if n != 1 else ''}, senhor." if n else \
        "Senhor, não encontrei esse lembrete."


def _aviso_na_tela(texto):
    # MB_ICONINFORMATION | MB_TOPMOST | MB_SETFOREGROUND
    threading.Thread(target=lambda: ctypes.windll.user32.MessageBoxW(0, texto, "GHOST - Lembrete", 0x40 | 0x40000 | 0x10000),
                     daemon=True).start()


def _disparar(l, atrasado=False):
    frase = f"Senhor, lembrete{' que ficou pendente' if atrasado else ''}: {l['texto']}."
    print(f"\n[LEMBRETE]: {l['quando']} -> {l['texto']}")
    _aviso_na_tela(f"{l['quando']}\n\n{l['texto']}")
    if _falar:
        _falar(frase)


def _loop():
    primeira = True
    while True:
        try:
            agora = datetime.now()
            with _trava:
                lista = _carregar()
                vencidos = [l for l in lista if _data(l) and _data(l) <= agora]
                estragados = [l for l in lista if not _data(l)]
                if vencidos or estragados:
                    _gravar([l for l in lista if l not in vencidos and l not in estragados])
            for l in vencidos:
                atraso = agora - _data(l)
                if atraso <= timedelta(hours=AVISAR_ATRASADOS_HORAS):
                    _disparar(l, atrasado=primeira and atraso > timedelta(minutes=2))
            primeira = False
        except Exception as e:
            print(f"\n[LEMBRETE]: erro: {e!r}")
        time.sleep(15)


def iniciar(falar):
    global _falar
    _falar = falar
    threading.Thread(target=_loop, daemon=True).start()
