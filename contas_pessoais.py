"""
GHOST - E-mail e agenda de CONTAS PESSOAIS (somente leitura), sem Google Cloud.

E-MAIL (IMAP com "senha de app"): funciona com Gmail pessoal, Yahoo, iCloud e outros.
No .env, uma conta por número (1, 2, 3...):
  EMAIL1_NOME=pessoal
  EMAIL1_USUARIO=seuemail@gmail.com
  EMAIL1_SENHA=senha de app de 16 letras   (Gmail: myaccount.google.com > Segurança > Senhas de app;
                                            exige verificação em 2 etapas ligada)
  EMAIL1_SERVIDOR=imap.gmail.com           (opcional: descoberto pelo domínio)

AGENDA (link secreto iCal): Google Agenda > Configurações > sua agenda >
"Endereço secreto no formato iCal" (Outlook: Calendário > Compartilhar > Publicar > ICS).
  AGENDA1_NOME=pessoal
  AGENDA1_URL=https://calendar.google.com/calendar/ical/.../basic.ics

Nada é marcado como lido nem alterado (IMAP em modo leitura + BODY.PEEK).
"""
import os
import re
import imaplib
import email
from email.header import decode_header, make_header
from email.utils import parseaddr
from datetime import datetime, timedelta, timezone

import requests

FUSO = timezone(timedelta(hours=-3))
SERVIDORES = {"gmail.com": "imap.gmail.com", "googlemail.com": "imap.gmail.com", "yahoo.com": "imap.mail.yahoo.com",
              "yahoo.com.br": "imap.mail.yahoo.com", "icloud.com": "imap.mail.me.com", "me.com": "imap.mail.me.com",
              "outlook.com": "outlook.office365.com", "hotmail.com": "outlook.office365.com",
              "live.com": "outlook.office365.com", "uol.com.br": "imap.uol.com.br", "bol.com.br": "imap.bol.com.br",
              "terra.com.br": "imap.terra.com.br"}


def _numeradas(prefixo, campos):
    """Lê EMAIL1_..., EMAIL2_... (ou AGENDA1_...) do ambiente."""
    itens = []
    for i in range(1, 10):
        d = {c.lower(): os.getenv(f"{prefixo}{i}_{c}", "").strip() for c in campos}
        if any(d.values()):
            d["nome"] = d.get("nome") or f"{prefixo.lower()} {i}"
            itens.append(d)
    return itens


def contas_email():
    return [c for c in _numeradas("EMAIL", ("NOME", "USUARIO", "SENHA", "SERVIDOR")) if c["usuario"] and c["senha"]]


def agendas():
    return [a for a in _numeradas("AGENDA", ("NOME", "URL")) if a["url"]]


def configurado():
    return bool(contas_email() or agendas())


def _filtrar(lista, conta):
    if not conta:
        return lista
    alvo = conta.lower()
    return [c for c in lista if alvo in c["nome"].lower()] or lista


def _txt(valor):
    try:
        return str(make_header(decode_header(valor or "")))
    except Exception:
        return valor or ""


# ---------------- e-mail ----------------
def emails(apenas_nao_lidos=True, remetente="", quantidade=8, conta=""):
    saida = []
    for c in _filtrar(contas_email(), conta):
        servidor = c.get("servidor") or SERVIDORES.get(c["usuario"].split("@")[-1].lower(), "imap." + c["usuario"].split("@")[-1])
        try:
            with imaplib.IMAP4_SSL(servidor, 993, timeout=15) as imap:
                imap.login(c["usuario"], c["senha"].replace(" ", ""))
                imap.select("INBOX", readonly=True)
                criterio = ["UNSEEN"] if apenas_nao_lidos else ["ALL"]
                if remetente:
                    criterio += ["FROM", f'"{remetente}"']
                _, dados = imap.search(None, *criterio)
                ids = dados[0].split()[-min(int(quantidade), 15):][::-1]
                linhas = []
                for i in ids:
                    _, msg = imap.fetch(i, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
                    cab = email.message_from_bytes(msg[0][1])
                    nome, endereco = parseaddr(_txt(cab.get("From")))
                    linhas.append(f"De: {nome or endereco} | Assunto: {_txt(cab.get('Subject')) or '(sem assunto)'}")
                total = len(dados[0].split())
                cabecalho = f"[{c['nome']}] {total} {'não lido(s)' if apenas_nao_lidos else 'e-mail(s)'}"
                saida.append(cabecalho + (":\n" + "\n".join(linhas) if linhas else "."))
        except imaplib.IMAP4.error as e:
            saida.append(f"[{c['nome']}] login recusado ({e}). Confira a senha de app.")
        except Exception as e:
            saida.append(f"[{c['nome']}] indisponível ({e}).")
    return "\n".join(saida) or "Nenhuma conta de e-mail pessoal configurada."


def contar_nao_lidos():
    total = 0
    for c in contas_email():
        r = emails(True, "", 1, c["nome"])
        m = re.search(r"\] (\d+) não lido", r)
        total += int(m.group(1)) if m else 0
    return total


# ---------------- agenda ----------------
def _intervalo(periodo):
    hoje = datetime.now(FUSO).replace(hour=0, minute=0, second=0, microsecond=0)
    if periodo == "amanha":
        return hoje + timedelta(days=1), hoje + timedelta(days=2)
    if periodo == "semana":
        return datetime.now(FUSO), hoje + timedelta(days=7)
    if periodo and periodo[:4].isdigit():
        ini = datetime.strptime(periodo[:10], "%Y-%m-%d").replace(tzinfo=FUSO)
        return ini, ini + timedelta(days=1)
    return hoje, hoje + timedelta(days=1)


def agenda(periodo="hoje", conta=""):
    import icalendar
    import recurring_ical_events
    ini, fim = _intervalo(periodo)
    saida = []
    for a in _filtrar(agendas(), conta):
        try:
            cal = icalendar.Calendar.from_ical(requests.get(a["url"], timeout=15).content)
            eventos = []
            for ev in recurring_ical_events.of(cal).between(ini, fim):
                inicio = ev.get("DTSTART").dt
                if isinstance(inicio, datetime):
                    quando = (inicio.astimezone(FUSO) if inicio.tzinfo else inicio).strftime("%d/%m %H:%M")
                else:
                    quando = inicio.strftime("%d/%m") + " (dia todo)"
                local = f" — {ev.get('LOCATION')}" if ev.get("LOCATION") else ""
                eventos.append((quando, f"{quando}: {ev.get('SUMMARY', '(sem título)')}{local}"))
            eventos.sort()
            saida.append(f"[{a['nome']}] " + ("\n" + "\n".join(e for _, e in eventos) if eventos else "nenhum compromisso."))
        except Exception as e:
            saida.append(f"[{a['nome']}] agenda indisponível ({e}).")
    return "\n".join(saida) or "Nenhuma agenda pessoal configurada."
