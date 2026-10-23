"""
GHOST - Abrir e fechar QUALQUER aplicativo instalado.

Usa a mesma lista do Menu Iniciar do Windows (Get-StartApps), que inclui
programas comuns (Excel, AnyDesk, Protheus...) e apps da Microsoft Store.
A lista fica em cache (apps_cache.json) e é atualizada 1x por dia ou quando
um nome não é encontrado.
"""
import difflib
import json
import os
import re
import subprocess
import time
import unicodedata

import pyautogui

from ghost.nucleo import arquivo, caminhos

ARQUIVO_CACHE = caminhos.dado("apps_cache.json")
VALIDADE_CACHE = 24 * 3600
RELEITURA_MINIMA = 600    # não relê o Menu Iniciar (2-5 s) mais de uma vez a cada 10 min
_ultima_leitura = 0.0

# Apelidos falados -> nome no Menu Iniciar (acrescente os seus)
APELIDOS = {
    "excel": "Excel", "word": "Word", "powerpoint": "PowerPoint", "outlook": "Outlook",
    "navegador": "Google Chrome", "chrome": "Google Chrome", "edge": "Microsoft Edge",
    "vs code": "Visual Studio Code", "vscode": "Visual Studio Code",
    "configuracoes": "Configurações", "explorador": "Explorador de Arquivos",
    "zap": "WhatsApp", "whats": "WhatsApp",
}

CONFIANCA_DIRETA = 0.80   # acima disso abre direto
CONFIANCA_MINIMA = 0.68   # entre os dois: pergunta "quis dizer X?"


def normalizar(t):
    t = unicodedata.normalize("NFD", t.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", t)).strip()


def _ler_menu_iniciar():
    cmd = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
           "Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True,
                       timeout=60, creationflags=0x08000000)  # sem janela
    dados = json.loads(r.stdout.decode("utf-8-sig", errors="replace") or "[]")
    if isinstance(dados, dict):
        dados = [dados]
    return [{"nome": d["Name"], "id": d["AppID"]} for d in dados if d.get("Name") and d.get("AppID")]


def _cache():
    try:
        return arquivo.ler_json(ARQUIVO_CACHE, []) or []
    except arquivo.ArquivoCorrompido:
        return []


def listar(forcar=False):
    global _ultima_leitura
    try:
        recente = time.time() - os.path.getmtime(ARQUIVO_CACHE) < VALIDADE_CACHE
    except OSError:
        recente = False
    if recente and (not forcar or time.time() - _ultima_leitura < RELEITURA_MINIMA):
        apps = _cache()
        if apps:
            return apps
    _ultima_leitura = time.time()
    try:
        apps = _ler_menu_iniciar()
    except Exception as e:                       # PowerShell lento/travado: usa a lista antiga
        print(f"\n[APPS]: não consegui ler o Menu Iniciar ({e}); usando a lista guardada.")
        return _cache()
    if apps:                                     # nunca troca uma lista boa por uma vazia
        arquivo.salvar_json(ARQUIVO_CACHE, apps, indent=None)
    return apps or _cache()


def _pontuar(alvo, nome):
    n = normalizar(nome)
    if alvo == n:
        return 1.0
    if re.search(rf"\b{re.escape(alvo)}\b", n):          # "excel" dentro de "Microsoft Excel"
        return 0.92 - min(len(n) - len(alvo), 30) * 0.003
    return difflib.SequenceMatcher(None, alvo, n).ratio()


def encontrar(nome_falado):
    """Retorna (app, confiança) do app mais parecido."""
    alvo = normalizar(nome_falado)
    alvo = normalizar(APELIDOS.get(alvo, alvo))
    for tentativa in (False, True):  # 2ª tentativa: atualiza a lista (app recém-instalado)
        apps = listar(forcar=tentativa)
        ranking = sorted(((_pontuar(alvo, a["nome"]), a) for a in apps), key=lambda x: -x[0])
        if ranking and ranking[0][0] >= CONFIANCA_DIRETA:
            return ranking[0][1], ranking[0][0]
    return (ranking[0][1], ranking[0][0]) if ranking else (None, 0.0)


def abrir(app):
    """Abre pelo identificador do Menu Iniciar (funciona para .exe, atalhos e apps da Store)."""
    subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app['id']}"])


def fechar(nome_falado):
    """Fecha janelas cujo título contém o nome. Retorna quantas fechou."""
    alvo = normalizar(APELIDOS.get(normalizar(nome_falado), nome_falado))
    fechadas = 0
    for janela in pyautogui.getAllWindows():
        titulo = normalizar(janela.title)
        # palavra inteira: "aba" não fecha "Trabalho.xlsx"
        if titulo and alvo and re.search(rf"\b{re.escape(alvo)}\b", titulo) and "ghost" not in titulo:
            try:
                janela.close(); fechadas += 1
            except Exception:
                pass
    return fechadas
