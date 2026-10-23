"""
GHOST - Resumo da manhã.

Diga "Ghost, bom dia" (ou "resumo do dia"). Ele também fala sozinho na
primeira vez que o Ghost abrir de manhã (uma vez por dia).
Conteúdo: dia e data, clima da sua cidade (Open-Meteo, gratuito, sem chave),
lembretes de hoje e, quando a conta Google estiver conectada, a agenda do dia
e quantos e-mails não lidos há.
A cidade fica em dados/preferencias.json ("cidade") e muda por voz:
"Ghost, minha cidade é Barueri".
"""
from datetime import datetime

import requests

from ghost.nucleo import preferencias

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
    """Latitude/longitude da cidade (guardadas junto com o nome, para trocar de cidade sem confusão)."""
    salvo = preferencias.carregar().get("cidade_coord")
    if isinstance(salvo, dict) and salvo.get("cidade") == cidade and len(salvo.get("coord") or []) == 2:
        return salvo["coord"]
    r = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                     params={"name": cidade, "count": 1, "language": "pt", "countryCode": "BR"}, timeout=8)
    r.raise_for_status()
    resultados = r.json().get("results") or []
    if not resultados:
        raise ValueError(f"cidade '{cidade}' não encontrada")
    coord = [resultados[0]["latitude"], resultados[0]["longitude"]]
    preferencias.definir("cidade_coord", {"cidade": cidade, "coord": coord})
    return coord


def clima(cidade=None):
    cidade = cidade or preferencias.carregar().get("cidade", "Santana de Parnaíba")
    lat, lon = _coordenadas(cidade)
    r = requests.get("https://api.open-meteo.com/v1/forecast", timeout=8, params={
        "latitude": lat, "longitude": lon, "current": "temperature_2m,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
        "timezone": "America/Sao_Paulo", "forecast_days": 1})
    r.raise_for_status()
    w = r.json()
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


def _falar_eventos(itens):
    """[(data, hora|None, título, local)] -> "reunião às 09:00; aniversário (dia todo)"."""
    return "; ".join(f"{t} às {h}" if h else f"{t} (o dia todo)" for _, h, t, _ in itens[:5])


def _lembretes_de_hoje():
    from ghost.servicos import lembretes
    hoje = datetime.now().date()
    itens = sorted(((d, l) for l in lembretes._carregar() if (d := lembretes._data(l)) and d.date() == hoje),
                   key=lambda x: x[0])
    if not itens:
        return ""
    return "Lembretes de hoje: " + "; ".join(f"às {d:%H:%M}, {l.get('texto', '')}" for d, l in itens) + "."


def _google():
    from ghost.servicos import google_conta
    if not google_conta.configurado():
        return ""
    partes = []
    try:
        itens = google_conta.eventos("hoje")
        if itens:
            partes.append(f"Na agenda, {len(itens)} compromisso{'s' if len(itens) > 1 else ''}: "
                          + _falar_eventos(itens) + ".")
    except Exception as e:
        print(f"\n[RESUMO]: agenda Google indisponível ({e})")
    try:
        em = google_conta.emails(True, "", 15)
        if not em.startswith("Nenhum"):
            n = len(em.split("\n"))
            partes.append(f"Há {n}{' ou mais' if n >= 15 else ''} e-mails não lidos.")
    except Exception as e:
        print(f"\n[RESUMO]: e-mail Google indisponível ({e})")
    return " ".join(partes)


def _pessoais():
    from ghost.servicos import contas_pessoais
    if not contas_pessoais.configurado():
        return ""
    partes = []
    try:
        itens = [e for _, lista in contas_pessoais.eventos("hoje") if isinstance(lista, list) for e in lista]
        if itens:
            itens.sort(key=lambda x: (x[0], x[1] is not None, x[1] or ""))
            partes.append("Na agenda pessoal: " + _falar_eventos(itens) + ".")
    except Exception as e:
        print(f"\n[RESUMO]: agenda pessoal indisponível ({e})")
    try:
        if contas_pessoais.contas_email():
            n = contas_pessoais.contar_nao_lidos()
            if n:
                partes.append(f"E {n} e-mail{'s' if n > 1 else ''} pessoal{'is' if n > 1 else ''} "
                              f"não lido{'s' if n > 1 else ''}.")
    except Exception as e:
        print(f"\n[RESUMO]: e-mail pessoal indisponível ({e})")
    return " ".join(partes)


def gerar():
    agora = datetime.now()
    from ghost.ia.pessoas import DONO
    abertura = "Bom dia" if agora.hour < 12 else "Boa tarde" if agora.hour < 18 else "Boa noite"
    partes = [f"{abertura}, {DONO}. Hoje é "
              f"{DIAS[agora.weekday()]}, {agora.day} de {MESES[agora.month - 1]}."]
    try:
        partes.append(clima())
    except Exception as e:
        print(f"\n[RESUMO]: clima indisponível ({e})")
    tem_lembrete = False
    for fonte in (_lembretes_de_hoje, _google, _pessoais):
        try:
            parte = fonte()
        except Exception as e:                 # uma fonte com defeito não derruba o resumo inteiro
            print(f"\n[RESUMO]: {fonte.__name__} falhou ({e!r})")
            parte = ""
        if parte:
            partes.append(parte)
            tem_lembrete = tem_lembrete or fonte is _lembretes_de_hoje
    if not tem_lembrete:
        partes.append("Nenhum lembrete marcado para hoje.")
    preferencias.definir("ultimo_resumo", agora.strftime("%Y-%m-%d"))
    return " ".join(partes)


def deve_resumir_agora():
    """True na primeira vez do dia, de manhã."""
    agora = datetime.now()
    return (HORARIO_MANHA[0] <= agora.hour < HORARIO_MANHA[1]
            and preferencias.carregar().get("ultimo_resumo") != agora.strftime("%Y-%m-%d"))
