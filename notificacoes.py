"""
GHOST - Avisa por voz as notificações do Windows (WhatsApp, Outlook, Teams...).

Padrão discreto: fala só o APP e QUEM mandou ("Senhor, WhatsApp: Leonard").
O conteúdo não é lido em voz alta (há outras pessoas na sala); para ouvir:
"Ghost, o que diz a notificação?" / "quais notificações chegaram?".
Preferências (preferencias.json, mudam por voz):
  notificacoes_ativas  true/false         "ativar/desativar notificações"
  notificacoes_ler_texto false/true       "ler o texto das notificações" / "não ler o texto"
  notificacoes_apps    ["whatsapp", ...]  quais apps são anunciados
Primeiro uso: o Windows pode pedir permissão (Configurações > Privacidade >
Notificações > permitir que apps acessem as notificações).
"""
import re
import time
import asyncio
import threading
from collections import deque
from datetime import datetime

import preferencias

INTERVALO = 4
APPS_PADRAO = ["whatsapp", "outlook", "teams", "telegram", "gmail", "agenda", "calendar", "email", "e-mail"]
_recentes = deque(maxlen=30)          # para "quais notificações chegaram?"
_vistos = set()
_pendentes = deque(maxlen=5)
_falar = _ocupado = None
_silencio_ate = 0.0
_fonte = None                          # "winrt" ou "banco"
_erro_avisado = False


def _pref(chave, padrao):
    return preferencias.carregar().get(chave, padrao)


# ---------------- leitura: WinRT (oficial) ----------------
async def _winrt_ler():
    from winrt.windows.ui.notifications.management import UserNotificationListener, UserNotificationListenerAccessStatus
    from winrt.windows.ui.notifications import NotificationKinds, KnownNotificationBindings
    ouvinte = UserNotificationListener.current
    if await ouvinte.request_access_async() != UserNotificationListenerAccessStatus.ALLOWED:
        raise PermissionError("acesso às notificações negado no Windows")
    saida = []
    for n in await ouvinte.get_notifications_async(NotificationKinds.TOAST):
        try:
            app = n.app_info.display_info.display_name
        except Exception:
            app = "?"
        textos = []
        try:
            b = n.notification.visual.get_binding(KnownNotificationBindings.toast_generic)
            textos = [t.text for t in b.get_text_elements()] if b else []
        except Exception:
            pass
        saida.append((str(n.id), app, textos))
    return saida


# ---------------- leitura: banco de notificações do Windows (reserva) ----------------
def _banco_ler():
    import os, re, sqlite3
    caminho = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows\Notifications\wpndatabase.db")
    con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True, timeout=2)
    try:
        linhas = con.execute("SELECT n.Id, h.PrimaryId, n.Payload FROM Notification n "
                             "JOIN NotificationHandler h ON h.RecordId = n.HandlerId "
                             "WHERE n.Type = 'toast' ORDER BY n.Id DESC LIMIT 40").fetchall()
    finally:
        con.close()
    saida = []
    for nid, app_id, payload in linhas:
        xml = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else str(payload)
        textos = [re.sub(r"<[^>]+>", "", t).strip() for t in re.findall(r"<text[^>]*>(.*?)</text>", xml, re.S)]
        app = _nome_app(app_id or "")
        saida.append((f"b{nid}", app, [t for t in textos if t]))
    return saida


CONHECIDOS = {"whatsapp": "WhatsApp", "outlook": "Outlook", "teams": "Teams", "telegram": "Telegram",
              "chrome": "Chrome", "msedge": "Edge", "edge": "Edge", "gmail": "Gmail", "calendar": "Agenda",
              "mail": "E-mail", "slack": "Slack", "discord": "Discord", "spotify": "Spotify", "onedrive": "OneDrive"}


def _nome_app(app_id):
    """'5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App' -> 'WhatsApp'."""
    baixo = app_id.lower()
    for chave, nome in CONHECIDOS.items():
        if chave in baixo:
            return nome
    base = app_id.split("!")[0].split("\\")[-1]
    partes = [p for p in base.split("_")[0].split(".") if p and not re.fullmatch(r"[0-9A-Fa-f]{6,}", p)]
    return partes[-1] if partes else (app_id or "?")


def _ler():
    global _fonte
    if _fonte in (None, "winrt"):
        try:
            r = asyncio.run(_winrt_ler())
            _fonte = "winrt"
            return r
        except Exception as e:
            if _fonte is None:
                print(f"\n[NOTIFICAÇÕES]: leitura oficial indisponível ({e}); usando o banco do Windows.")
            _fonte = "banco"
    return _banco_ler()


# ---------------- anúncio ----------------
def _interessa(app):
    a = app.lower()
    return any(p in a for p in _pref("notificacoes_apps", APPS_PADRAO)) and "python" not in a


def _frase(app, textos, completo=False):
    quem = textos[0] if textos else ""
    if completo or _pref("notificacoes_ler_texto", False):
        resto = " ".join(textos[1:])[:160]
        return f"Senhor, {app}: {quem}. {resto}".strip()
    return f"Senhor, {app}: {quem}." if quem else f"Senhor, nova notificação do {app}."


def _loop():
    global _erro_avisado
    primeira = True
    while True:
        try:
            for nid, app, textos in _ler():
                if nid in _vistos:
                    continue
                _vistos.add(nid)
                if primeira or not _interessa(app):
                    continue                       # na 1ª leitura só marca as antigas como vistas
                item = {"t": time.time(), "app": app, "textos": textos}
                _recentes.append(item)
                _pendentes.append(item)
            primeira = False
            _anunciar()
        except Exception as e:
            if not _erro_avisado:
                print(f"\n[NOTIFICAÇÕES]: não consegui ler ({e}). Tento de novo em segundo plano.")
                _erro_avisado = True
        time.sleep(INTERVALO)


def _anunciar():
    if not _pendentes:
        return
    if not _pref("notificacoes_ativas", True) or time.time() < _silencio_ate:
        _pendentes.clear()                         # silenciado: não acumula para falar depois
        return
    if _ocupado and _ocupado():
        return                                     # espera você terminar de falar com ele
    while _pendentes:
        item = _pendentes.popleft()
        if time.time() - item["t"] < 120 and _falar:
            _falar(_frase(item["app"], item["textos"]))


def listar(quantidade=5, app=""):
    """Para a IA: últimas notificações (com o texto)."""
    itens = [i for i in _recentes if not app or app.lower() in i["app"].lower()][-int(quantidade):]
    if not itens:
        return "Nenhuma notificação recebida desde que o Ghost iniciou."
    return "\n".join(f"[{datetime.fromtimestamp(i['t']):%H:%M}] {i['app']}: {' | '.join(i['textos'])[:300]}" for i in itens)


def silenciar(minutos):
    global _silencio_ate
    _silencio_ate = time.time() + minutos * 60


def iniciar(falar, ocupado):
    global _falar, _ocupado
    _falar, _ocupado = falar, ocupado
    threading.Thread(target=_loop, daemon=True).start()
