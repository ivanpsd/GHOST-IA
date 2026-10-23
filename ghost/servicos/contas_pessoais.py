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
import email
import imaplib
import os
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import parseaddr

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
    """Conta pelo nome: exato primeiro, depois "contém". Nome que não existe -> lista vazia (não lê todas)."""
    if not conta:
        return lista
    alvo = conta.strip().casefold()
    return ([c for c in lista if c["nome"].casefold() == alvo]
            or [c for c in lista if alvo in c["nome"].casefold()])


def _sem_conta(lista, conta, tipo):
    nomes = ", ".join(c["nome"] for c in lista) or "nenhuma"
    return f"Nenhuma {tipo} pessoal chamada '{conta}'. Configuradas: {nomes}."


def _txt(valor):
    try:
        return str(make_header(decode_header(valor or "")))
    except Exception:
        return valor or ""


# ---------------- e-mail ----------------
def _servidor(c):
    dominio = c["usuario"].split("@")[-1].lower()
    return c.get("servidor") or SERVIDORES.get(dominio, "imap." + dominio)


def _buscar(c, apenas_nao_lidos, remetente, quantidade):
    """(total, linhas) de uma conta. quantidade=0 só conta, sem baixar cabeçalhos."""
    with imaplib.IMAP4_SSL(_servidor(c), 993, timeout=15) as imap:
        imap.login(c["usuario"], c["senha"].replace(" ", ""))
        imap.select("INBOX", readonly=True)
        criterio = ["UNSEEN"] if apenas_nao_lidos else ["ALL"]
        if remetente and remetente.isascii():
            criterio += ["FROM", '"' + remetente.replace("\\", "").replace('"', "") + '"']
            _, dados = imap.search(None, *criterio)
        elif remetente:                       # acento no nome: busca em UTF-8 (literal)
            imap.literal = remetente.encode("utf-8")
            _, dados = imap.search("UTF-8", *criterio, "FROM")
        else:
            _, dados = imap.search(None, *criterio)
        todos = (dados[0] or b"").split()
        linhas = []
        for i in (todos[-quantidade:][::-1] if quantidade > 0 else []):
            _, msg = imap.fetch(i, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if not msg or not isinstance(msg[0], tuple):
                continue
            cab = email.message_from_bytes(msg[0][1])
            nome, endereco = parseaddr(_txt(cab.get("From")))
            linhas.append(f"De: {nome or endereco} | Assunto: {_txt(cab.get('Subject')) or '(sem assunto)'}")
        return len(todos), linhas


def emails(apenas_nao_lidos=True, remetente="", quantidade=8, conta=""):
    try:
        quantidade = max(1, min(int(quantidade), 15))
    except (TypeError, ValueError):
        quantidade = 8
    todas = contas_email()
    lista = _filtrar(todas, conta)
    if conta and not lista:
        return _sem_conta(todas, conta, "conta de e-mail")
    saida = []
    for c in lista:
        try:
            total, linhas = _buscar(c, apenas_nao_lidos, (remetente or "").strip(), quantidade)
            cabecalho = f"[{c['nome']}] {total} {'não lido(s)' if apenas_nao_lidos else 'e-mail(s)'}"
            saida.append(cabecalho + (":\n" + "\n".join(linhas) if linhas else "."))
        except imaplib.IMAP4.error as e:
            saida.append(f"[{c['nome']}] login recusado ({e}). Confira a senha de app.")
        except Exception as e:
            saida.append(f"[{c['nome']}] indisponível ({e}).")
    return "\n".join(saida) or "Nenhuma conta de e-mail pessoal configurada."


def contar_nao_lidos():
    """Total de não lidos em todas as contas (contas com erro contam 0)."""
    total = 0
    for c in contas_email():
        try:
            total += _buscar(c, True, "", 0)[0]
        except Exception as e:
            print(f"\n[CONTAS PESSOAIS]: {c['nome']} indisponível ({e}).")
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


def eventos(periodo="hoje", conta=""):
    """[(nome_agenda, [(data, "HH:MM" ou None, título, local)]) ou (nome_agenda, erro_str)] em ordem cronológica."""
    import icalendar
    import recurring_ical_events
    ini, fim = _intervalo(periodo)
    saida = []
    for a in _filtrar(agendas(), conta):
        try:
            r = requests.get(a["url"], timeout=15)
            r.raise_for_status()
            cal = icalendar.Calendar.from_ical(r.content)
            itens = []
            for ev in recurring_ical_events.of(cal).between(ini, fim):
                inicio = ev.get("DTSTART").dt
                if isinstance(inicio, datetime):
                    inicio = inicio.astimezone(FUSO) if inicio.tzinfo else inicio
                    chave, dia, hora = (inicio.date(), 1, inicio.strftime("%H:%M")), inicio.date(), inicio.strftime("%H:%M")
                else:
                    chave, dia, hora = (inicio, 0, ""), inicio, None
                itens.append((chave, (dia, hora, str(ev.get("SUMMARY") or "(sem título)"), str(ev.get("LOCATION") or ""))))
            itens.sort(key=lambda x: x[0])
            saida.append((a["nome"], [e for _, e in itens]))
        except Exception as e:
            saida.append((a["nome"], f"agenda indisponível ({e})"))
    return saida


def agenda(periodo="hoje", conta=""):
    todas = agendas()
    if conta and not _filtrar(todas, conta):
        return _sem_conta(todas, conta, "agenda")
    saida = []
    for nome, itens in eventos(periodo, conta):
        if isinstance(itens, str):
            saida.append(f"[{nome}] {itens}.")
            continue
        linhas = [f"{d:%d/%m} {h or '(dia todo)'}: {t}" + (f" — {loc}" if loc else "") for d, h, t, loc in itens]
        saida.append(f"[{nome}] " + ("\n" + "\n".join(linhas) if linhas else "nenhum compromisso."))
    return "\n".join(saida) or "Nenhuma agenda pessoal configurada."
