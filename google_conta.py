"""
GHOST - Agenda e e-mail do Google (SOMENTE LEITURA).

"Como está minha agenda hoje?", "tenho reunião amanhã?",
"tenho e-mail novo?", "chegou e-mail da Deborah?"

O Ghost só LÊ: não envia, não apaga e não altera nada (permissões readonly).
Para os e-mails, só remetente, assunto e um trecho curto vão para a IA resumir.

Configuração (uma vez): coloque o credentials.json do Google Cloud na pasta do
Ghost e diga "Ghost, conectar minha conta Google" (abre o navegador para você
autorizar). O acesso fica em token_google.json (fora do Git).
"""
import os
from datetime import datetime, timedelta, timezone

PASTA_GHOST = os.path.dirname(os.path.abspath(__file__))
CREDENCIAIS = os.path.join(PASTA_GHOST, "credentials.json")
TOKEN = os.path.join(PASTA_GHOST, "token_google.json")
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly",
          "https://www.googleapis.com/auth/gmail.readonly"]
FUSO = timezone(timedelta(hours=-3))  # Brasília


def configurado():
    return os.path.exists(TOKEN)


def _credenciais(permitir_login=False):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    cred = Credentials.from_authorized_user_file(TOKEN, SCOPES) if os.path.exists(TOKEN) else None
    if cred and cred.expired and cred.refresh_token:
        cred.refresh(Request())
    elif not cred or not cred.valid:
        if not permitir_login:
            raise RuntimeError("conta Google não conectada. Diga: Ghost, conectar minha conta Google")
        if not os.path.exists(CREDENCIAIS):
            raise RuntimeError("falta o arquivo credentials.json na pasta do Ghost")
        from google_auth_oauthlib.flow import InstalledAppFlow
        cred = InstalledAppFlow.from_client_secrets_file(CREDENCIAIS, SCOPES).run_local_server(
            port=0, prompt="consent", authorization_prompt_message="",
            success_message="GHOST conectado. Pode fechar esta aba.")
    with open(TOKEN, "w", encoding="utf-8") as f:
        f.write(cred.to_json())
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


def agenda(periodo="hoje"):
    """periodo: 'hoje', 'amanha', 'semana' ou 'AAAA-MM-DD'. Retorna texto com os eventos."""
    agora = datetime.now(FUSO)
    hoje = agora.replace(hour=0, minute=0, second=0, microsecond=0)
    if periodo == "amanha":
        ini, fim = hoje + timedelta(days=1), hoje + timedelta(days=2)
    elif periodo == "semana":
        ini, fim = agora, hoje + timedelta(days=7)
    elif periodo and periodo[:4].isdigit():
        ini = datetime.strptime(periodo[:10], "%Y-%m-%d").replace(tzinfo=FUSO); fim = ini + timedelta(days=1)
    else:
        ini, fim = hoje, hoje + timedelta(days=1)
    r = _servico("calendar", "v3").events().list(
        calendarId="primary", timeMin=ini.isoformat(), timeMax=fim.isoformat(),
        singleEvents=True, orderBy="startTime", maxResults=20).execute()
    linhas = []
    for e in r.get("items", []):
        inicio = e["start"].get("dateTime") or e["start"].get("date")
        quando = (datetime.fromisoformat(inicio).astimezone(FUSO).strftime("%d/%m %H:%M")
                  if "T" in inicio else f"{inicio[8:10]}/{inicio[5:7]} (dia todo)")
        local = f" — {e['location']}" if e.get("location") else ""
        linhas.append(f"{quando}: {e.get('summary', '(sem título)')}{local}")
    return "\n".join(linhas) or f"Nenhum compromisso ({periodo})."


def emails(apenas_nao_lidos=True, remetente="", quantidade=8):
    """Lista remetente, assunto e trecho curto dos e-mails da caixa de entrada."""
    q = "in:inbox" + (" is:unread" if apenas_nao_lidos else "") + (f" from:{remetente}" if remetente else "")
    svc = _servico("gmail", "v1")
    ids = svc.users().messages().list(userId="me", q=q, maxResults=min(int(quantidade), 15)).execute().get("messages", [])
    linhas = []
    for m in ids:
        msg = svc.users().messages().get(userId="me", id=m["id"], format="metadata",
                                         metadataHeaders=["From", "Subject", "Date"]).execute()
        cab = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
        de = cab.get("From", "").split("<")[0].strip().strip('"') or cab.get("From", "")
        linhas.append(f"De: {de} | Assunto: {cab.get('Subject', '(sem assunto)')} | {msg.get('snippet', '')[:100]}")
    return "\n".join(linhas) or ("Nenhum e-mail não lido." if apenas_nao_lidos else "Nenhum e-mail encontrado.")
