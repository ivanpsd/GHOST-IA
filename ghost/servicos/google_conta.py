"""
GHOST - Agenda e e-mail do Google (SOMENTE LEITURA).

"Como está minha agenda hoje?", "tenho reunião amanhã?",
"tenho e-mail novo?", "chegou e-mail da Deborah?"

O Ghost só LÊ: não envia, não apaga e não altera nada (permissões readonly).
Para os e-mails, só remetente, assunto e um trecho curto vão para a IA resumir.

Configuração (uma vez): coloque o credentials.json do Google Cloud na pasta do
Ghost (dados/credentials.json) e diga "Ghost, conectar minha conta Google" (abre o
navegador para você autorizar). O acesso fica em dados/token_google.json (fora do Git).
"""
import os
import threading
from datetime import datetime, timedelta, timezone

from ghost.nucleo import arquivo, caminhos

CREDENCIAIS = caminhos.dado("credentials.json")
TOKEN = caminhos.dado("token_google.json")
_trava = threading.Lock()
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly",
          "https://www.googleapis.com/auth/gmail.readonly"]
FUSO = timezone(timedelta(hours=-3))  # Brasília


def configurado():
    return os.path.exists(TOKEN)


def _login():
    if not os.path.exists(CREDENCIAIS):
        raise RuntimeError("falta o arquivo credentials.json na pasta dados do Ghost")
    from google_auth_oauthlib.flow import InstalledAppFlow
    return InstalledAppFlow.from_client_secrets_file(CREDENCIAIS, SCOPES).run_local_server(
        port=0, prompt="consent", authorization_prompt_message="", timeout_seconds=300,
        success_message="GHOST conectado. Pode fechar esta aba.")


def _credenciais(permitir_login=False):
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    with _trava:                                   # duas consultas juntas não renovam/gravam o token ao mesmo tempo
        cred = None
        if os.path.exists(TOKEN):
            try:
                cred = Credentials.from_authorized_user_file(TOKEN, SCOPES)
            except (ValueError, KeyError) as e:    # token.json estragado
                print(f"\n[GOOGLE]: token inválido ({e}); será preciso conectar de novo.")
        if cred and cred.valid:
            return cred
        if cred and cred.expired and cred.refresh_token:
            try:
                cred.refresh(Request())
                arquivo.salvar_texto(TOKEN, cred.to_json())
                return cred
            except RefreshError as e:              # acesso revogado ou senha trocada
                print(f"\n[GOOGLE]: autorização expirou ({e}).")
                if not permitir_login:
                    raise RuntimeError("a autorização do Google expirou. Diga: Ghost, conectar minha conta Google") from e
        if not permitir_login:
            raise RuntimeError("conta Google não conectada. Diga: Ghost, conectar minha conta Google")
        cred = _login()
        arquivo.salvar_texto(TOKEN, cred.to_json())
        return cred


def conectar():
    """Abre o navegador para autorizar (somente leitura). Retorna a frase para o Ghost falar."""
    try:
        _credenciais(permitir_login=True)
        return "Conta Google conectada, senhor. Agora posso ler sua agenda e seus e-mails."
    except Exception as e:
        return f"Senhor, não consegui conectar: {e}."


def _servico(nome, versao):
    from googleapiclient.discovery import build
    return build(nome, versao, credentials=_credenciais(), cache_discovery=False)


def _intervalo(periodo):
    agora = datetime.now(FUSO)
    hoje = agora.replace(hour=0, minute=0, second=0, microsecond=0)
    if periodo == "amanha":
        return hoje + timedelta(days=1), hoje + timedelta(days=2)
    if periodo == "semana":
        return agora, hoje + timedelta(days=7)
    if periodo and periodo[:4].isdigit():
        ini = datetime.strptime(periodo[:10], "%Y-%m-%d").replace(tzinfo=FUSO)
        return ini, ini + timedelta(days=1)
    return hoje, hoje + timedelta(days=1)


def eventos(periodo="hoje"):
    """[(data, "HH:MM" ou None se for o dia todo, título, local)] em ordem cronológica."""
    ini, fim = _intervalo(periodo)
    r = _servico("calendar", "v3").events().list(
        calendarId="primary", timeMin=ini.isoformat(), timeMax=fim.isoformat(),
        singleEvents=True, orderBy="startTime", maxResults=20).execute()
    saida = []
    for e in r.get("items", []):
        inicio = e.get("start", {}).get("dateTime") or e.get("start", {}).get("date")
        if not inicio:
            continue
        if "T" in inicio:
            dt = datetime.fromisoformat(inicio.replace("Z", "+00:00")).astimezone(FUSO)
            saida.append((dt.date(), dt.strftime("%H:%M"), e.get("summary") or "(sem título)", e.get("location") or ""))
        else:
            saida.append((datetime.strptime(inicio, "%Y-%m-%d").date(), None,
                          e.get("summary") or "(sem título)", e.get("location") or ""))
    return saida


def agenda(periodo="hoje"):
    """periodo: 'hoje', 'amanha', 'semana' ou 'AAAA-MM-DD'. Retorna texto com os eventos."""
    linhas = [f"{d:%d/%m} {h or '(dia todo)'}: {t}" + (f" — {loc}" if loc else "") for d, h, t, loc in eventos(periodo)]
    return "\n".join(linhas) or f"Nenhum compromisso ({periodo})."


def emails(apenas_nao_lidos=True, remetente="", quantidade=8):
    """Lista remetente, assunto e trecho curto dos e-mails da caixa de entrada."""
    try:
        quantidade = max(1, min(int(quantidade), 15))
    except (TypeError, ValueError):
        quantidade = 8
    remetente = (remetente or "").replace('"', "").strip()
    q = "in:inbox" + (" is:unread" if apenas_nao_lidos else "") + (f' from:"{remetente}"' if remetente else "")
    svc = _servico("gmail", "v1")
    ids = svc.users().messages().list(userId="me", q=q, maxResults=quantidade).execute().get("messages", [])
    linhas = []
    for m in ids:
        msg = svc.users().messages().get(userId="me", id=m["id"], format="metadata",
                                         metadataHeaders=["From", "Subject", "Date"]).execute()
        cab = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        de = cab.get("From", "").split("<")[0].strip().strip('"') or cab.get("From", "")
        linhas.append(f"De: {de} | Assunto: {cab.get('Subject', '(sem assunto)')} | {msg.get('snippet', '')[:100]}")
    return "\n".join(linhas) or ("Nenhum e-mail não lido." if apenas_nao_lidos else "Nenhum e-mail encontrado.")
