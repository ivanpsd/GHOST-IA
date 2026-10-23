"""
GHOST - Resumo da manhã.

Diga "Ghost, bom dia" (ou "resumo do dia"). Ele também fala sozinho na
primeira vez que o Ghost abrir de manhã (uma vez por dia).
Conteúdo: dia e data, clima da sua cidade (Open-Meteo, gratuito, sem chave),
lembretes de hoje e, quando a conta Google estiver conectada, a agenda do dia
e quantos e-mails não lidos há.
A cidade fica em preferencias.json ("cidade") e muda por voz:
"Ghost, minha cidade é Barueri".
"""
import re
from datetime import datetime

import requests

import preferencias

DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
         "outubro", "novembro", "dezembro"]
HORARIO_MANHA = (5, 12)   # o resumo automático só acontece nesse horário

# Códigos de tempo da OMS (usados pelo Open-Meteo) -> descrição curta
TEMPO = {0: "céu limpo", 1: "poucas nuvens", 2: "parcialmente nublado", 3: "nublado", 45: "neblina", 48: "neblina",
         51: "garoa fraca", 53: "garoa", 55: "garoa forte", 61: "chuva fraca", 63: "chuva", 65: "chuva forte",
         66: "chuva congelante", 67: "chuva congelante", 71: "neve", 73: "neve", 75: "neve", 80: "pancadas de chuva",
         81: "pancadas de chuva", 82: "pancadas fortes de chuva", 95: "trovoadas", 96: "trovoadas com granizo",
         99: "trovoadas com granizo"}


def _coordenadas(cidade):
    p = preferencias.carregar()
    if p.get("cidade_coord") and p.get("cidade") == cidade:
        return p["cidade_coord"]
    r = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                     params={"name": cidade, "count": 1, "language": "pt", "countryCode": "BR"}, timeout=8).json()
    c = r["results"][0]
    coord = [c["latitude"], c["longitude"]]
    preferencias.definir("cidade_coord", coord)
    return coord


def clima(cidade=None):
    cidade = cidade or preferencias.carregar().get("cidade", "Santana de Parnaíba")
    lat, lon = _coordenadas(cidade)
    w = requests.get("https://api.open-meteo.com/v1/forecast", timeout=8, params={
        "latitude": lat, "longitude": lon, "current": "temperature_2m,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
        "timezone": "America/Sao_Paulo", "forecast_days": 1}).json()
    agora = round(w["current"]["temperature_2m"])
    d = w["daily"]
    desc = TEMPO.get(d["weather_code"][0], "tempo variável")
    chuva = d["precipitation_probability_max"][0] or 0
    frase = (f"Em {cidade}, {agora} graus agora, {desc}, mínima de {round(d['temperature_2m_min'][0])} "
             f"e máxima de {round(d['temperature_2m_max'][0])}.")
    if chuva >= 60:
        frase += f" Chance de chuva de {chuva} por cento: leve guarda-chuva."
    elif chuva >= 30:
        frase += f" Chance de chuva de {chuva} por cento."
    return frase


def _lembretes_de_hoje():
    import lembretes
    hoje = datetime.now().strftime("%Y-%m-%d")
    itens = sorted((l for l in lembretes._carregar() if l["quando"].startswith(hoje)), key=lambda x: x["quando"])
    if not itens:
        return ""
    return "Lembretes de hoje: " + "; ".join(f"às {l['quando'][11:16]}, {l['texto']}" for l in itens) + "."


def _google():
    import google_conta
    if not google_conta.configurado():
        return ""
    partes = []
    try:
        ag = google_conta.agenda("hoje")
        if not ag.startswith("Nenhum"):
            eventos = ag.split("\n")
            partes.append(f"Na agenda, {len(eventos)} compromisso{'s' if len(eventos) > 1 else ''}: " +
                          "; ".join(e.split(": ", 1)[-1] + " às " + e[6:11] for e in eventos[:5]) + ".")
        em = google_conta.emails(True, "", 15)
        if not em.startswith("Nenhum"):
            n = len(em.split("\n"))
            partes.append(f"Há {n}{'+' if n >= 15 else ''} e-mails não lidos.")
    except Exception as e:
        print(f"\n[RESUMO]: Google indisponível ({e})")
    return " ".join(partes)


def _pessoais():
    import contas_pessoais
    if not contas_pessoais.configurado():
        return ""
    partes = []
    try:
        if contas_pessoais.agendas():
            ag = contas_pessoais.agenda("hoje")
            eventos = [l for l in ag.split("\n") if re.match(r"\d{2}/\d{2}", l)]
            if eventos:
                partes.append("Na agenda pessoal: " + "; ".join(e.split(": ", 1)[-1] + " às " + e[6:11] for e in eventos[:5]) + ".")
        if contas_pessoais.contas_email():
            n = contas_pessoais.contar_nao_lidos()
            if n:
                partes.append(f"E {n} e-mail{'s' if n > 1 else ''} pessoal{'is' if n > 1 else ''} não lido{'s' if n > 1 else ''}.")
    except Exception as e:
        print(f"\n[RESUMO]: contas pessoais indisponíveis ({e})")
    return " ".join(partes)


def gerar():
    agora = datetime.now()
    from pessoas import DONO
    abertura = "Bom dia" if agora.hour < 12 else "Boa tarde" if agora.hour < 18 else "Boa noite"
    partes = [f"{abertura}, {DONO}. Hoje é "
              f"{DIAS[agora.weekday()]}, {agora.day} de {MESES[agora.month - 1]}."]
    try:
        partes.append(clima())
    except Exception as e:
        print(f"\n[RESUMO]: clima indisponível ({e})")
    for parte in (_lembretes_de_hoje(), _google(), _pessoais()):
        if parte:
            partes.append(parte)
    if len(partes) <= 2:
        partes.append("Nenhum lembrete marcado para hoje.")
    preferencias.definir("ultimo_resumo", agora.strftime("%Y-%m-%d"))
    return " ".join(partes)


def deve_resumir_agora():
    """True na primeira vez do dia, de manhã."""
    agora = datetime.now()
    return (HORARIO_MANHA[0] <= agora.hour < HORARIO_MANHA[1]
            and preferencias.carregar().get("ultimo_resumo") != agora.strftime("%Y-%m-%d"))
