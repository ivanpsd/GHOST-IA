"""
GHOST - Falar com o Ghost pelo celular (Telegram, grátis).

Você manda texto ou áudio para o seu bot e o Ghost executa no PC e responde por
escrito ali mesmo (não fala em voz alta no escritório). Não transmite a tela.

Configuração (uma vez):
1. No Telegram, fale com @BotFather -> /newbot -> escolha um nome -> copie o token.
2. No .env do Ghost:  TELEGRAM_TOKEN=123456:ABC...
3. Reinicie o Ghost e mande qualquer mensagem para o seu bot. Ele responde com o
   seu código; coloque no .env:  TELEGRAM_DONO=<código>   e reinicie de novo.
Só o dono (esse código) é atendido; qualquer outra pessoa recebe "não autorizado".
"""
import os
import threading
import time

import requests

API = "https://api.telegram.org/bot{token}/{metodo}"
_entregar = None


def _token():
    return os.getenv("TELEGRAM_TOKEN", "").strip()


def _dono():
    d = os.getenv("TELEGRAM_DONO", "").strip()
    return int(d) if d.lstrip("-").isdigit() else None


def _limpo(e):
    """Mensagem de erro sem o token (as exceções do requests trazem a URL com ele)."""
    t = str(e)
    tok = _token()
    return t.replace(tok, "***") if tok else t


def configurado():
    return bool(_token() and _dono())


def _chamar(metodo, timeout=15, **params):
    r = requests.post(API.format(token=_token(), metodo=metodo), json=params, timeout=timeout)
    r.raise_for_status()
    return r.json().get("result")


def enviar(chat, texto):
    for i in range(0, len(texto or "") or 1, 4000):   # limite do Telegram: 4096 caracteres
        try:
            _chamar("sendMessage", chat_id=chat, text=(texto or "…")[i:i + 4000])
        except Exception as e:
            print(f"\n[TELEGRAM]: não consegui enviar ({_limpo(e)}).")


def notificar(texto):
    """Manda uma mensagem para o dono (ex.: tarefa em segundo plano terminou)."""
    if configurado():
        enviar(_dono(), texto)


def _baixar_arquivo(file_id):
    info = _chamar("getFile", file_id=file_id)
    url = f"https://api.telegram.org/file/bot{_token()}/{info['file_path']}"
    return requests.get(url, timeout=30).content


def _loop():
    deslocamento = None
    erros = 0
    while True:
        try:
            r = requests.get(API.format(token=_token(), metodo="getUpdates"),
                             params={"timeout": 25, "offset": deslocamento}, timeout=35)
            j = r.json()
            if not j.get("ok"):          # token revogado (401), outro programa usando o bot (409)...
                raise RuntimeError(f"Telegram recusou: {j.get('error_code')} {j.get('description', '')}")
            atualizacoes = j.get("result", [])
            erros = 0
        except Exception as e:
            erros += 1
            if erros in (1, 10, 100):
                print(f"\n[TELEGRAM]: {_limpo(e)}; tentando de novo.")
            time.sleep(min(60, 5 * erros))
            continue
        for u in atualizacoes:
            deslocamento = u["update_id"] + 1
            msg = u.get("message") or {}
            chat = msg.get("chat", {}).get("id")
            if chat is None:
                continue
            dono = _dono()
            if dono is None:
                print(f"\n[TELEGRAM]: mensagem de {chat}. Se for você, coloque TELEGRAM_DONO={chat} no .env.")
                enviar(chat, f"Olá! Seu código é {chat}. Coloque TELEGRAM_DONO={chat} no arquivo .env do Ghost "
                             "e reinicie o Ghost para eu passar a atender você.")
                continue
            if chat != dono:
                print(f"\n[TELEGRAM]: mensagem recusada de {chat} (não é o dono).")
                enviar(chat, "Não autorizado.")
                continue
            try:
                if msg.get("text"):
                    _entregar({"texto": msg["text"], "origem": "telegram", "chat": chat})
                elif msg.get("voice") or msg.get("audio"):
                    arq = msg.get("voice") or msg.get("audio")
                    _entregar({"audio": _baixar_arquivo(arq["file_id"]), "nome_audio": "audio.ogg",
                               "origem": "telegram", "chat": chat})
                else:
                    enviar(chat, "Por enquanto entendo texto e áudio, senhor.")
            except Exception as e:
                enviar(chat, f"Erro ao receber: {_limpo(e)}")


def iniciar(entregar):
    global _entregar
    _entregar = entregar
    if not _token():
        return False
    threading.Thread(target=_loop, daemon=True).start()
    print("\n[TELEGRAM]: bot ligado" + ("." if _dono() else " (falta TELEGRAM_DONO: mande uma mensagem ao bot)."))
    return True
