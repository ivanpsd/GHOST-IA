"""
GHOST - Entender períodos falados: "mês passado", "de 1 a 15 de outubro", "semana passada", "ontem",
"de 01/10 até 15/10", "últimos 7 dias", "outubro", "do dia 5 até hoje".

interpretar(frase, hoje) -> (inicio, fim) como datetime.date, ou None se não houver período na frase.
Usado pelas skills gravadas que têm campos de data ("Da Data", "Até a Data" nos relatórios do Protheus).
"""
import re
import unicodedata
from datetime import date, timedelta

MESES = {"janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
         "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
         "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6, "jul": 7, "ago": 8, "set": 9, "out": 10,
         "nov": 11, "dez": 12}
NUMEROS = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6, "sete": 7,
           "oito": 8, "nove": 9, "dez": 10, "quinze": 15, "vinte": 20, "trinta": 30, "primeiro": 1}


def _norm(t):
    t = unicodedata.normalize("NFD", (t or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", t).strip()


def _fim_do_mes(ano, mes):
    return (date(ano + (mes == 12), mes % 12 + 1, 1) - timedelta(days=1))


def _ano_padrao(mes, hoje):
    """'outubro' dito em janeiro é o outubro passado."""
    return hoje.year if mes <= hoje.month else hoje.year - 1


def _data(dia, mes, ano, hoje):
    if ano is None:
        ano = hoje.year if (mes, dia) <= (hoje.month, hoje.day) else hoje.year - 1
    elif ano < 100:
        ano += 2000
    return date(ano, mes, dia)


RE_DATA = r"(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?"
RE_DIA_MES = r"(?:dia\s+)?(\d{1,2})(?:\s+de\s+(" + "|".join(sorted(MESES, key=len, reverse=True)) + r"))?(?:\s+de\s+(\d{4}))?"


def _segunda(d):
    return d - timedelta(days=d.weekday())


def interpretar(frase, hoje=None):
    hoje = hoje or date.today()
    t = _norm(frase)

    # 1. datas escritas: "de 01/10 a 15/10", "01/10/2026 até 15/10/2026", "dia 10/10"
    datas = re.findall(RE_DATA, t)
    if datas:
        try:
            ds = [_data(int(d), int(m), int(a) if a else None, hoje) for d, m, a in datas[:2]]
        except ValueError:
            ds = []
        if ds:
            if len(ds) == 1:
                fim = hoje if re.search(r"\bate hoje\b|\bate agora\b", t) else ds[0]
                return ds[0], fim
            return min(ds), max(ds)

    # 2. "de 1 a 15 de outubro", "do dia 5 até o dia 20", "do dia 5 até hoje"
    m = re.search(r"\bd[eo]\s+(?:dia\s+)?(\d{1,2})(?:\s+de\s+(\w+))?\s+(?:a|ate|ao)\s+(?:o\s+)?(?:dia\s+)?(\d{1,2}|hoje)"
                  r"(?:\s+de\s+(\w+))?(?:\s+de\s+(\d{4}))?", t)
    if m:
        d1, mes1, d2, mes2, ano = m.groups()
        mes2n = MESES.get(mes2 or "") or MESES.get(mes1 or "")
        mes1n = MESES.get(mes1 or "") or mes2n
        try:
            if d2 == "hoje":
                mes1n = mes1n or hoje.month
                ini = date(int(ano) if ano else _ano_padrao(mes1n, hoje), mes1n, int(d1))
                return ini, hoje
            mes1n, mes2n = mes1n or hoje.month, mes2n or hoje.month
            ano_n = int(ano) if ano else _ano_padrao(mes2n, hoje)
            ini = date(ano_n if mes1n <= mes2n else ano_n - 1, mes1n, int(d1))
            return ini, date(ano_n, mes2n, int(d2))
        except ValueError:
            pass

    # 3. expressões
    if re.search(r"\bhoje\b", t) and not re.search(r"\bate hoje\b", t):
        return hoje, hoje
    if re.search(r"\banteontem\b", t):
        d = hoje - timedelta(days=2)
        return d, d
    if re.search(r"\bontem\b", t):
        d = hoje - timedelta(days=1)
        return d, d
    m = re.search(r"\bultim[oa]s\s+(\d+|\w+)\s+dias\b", t)
    if m:
        n = int(m.group(1)) if m.group(1).isdigit() else NUMEROS.get(m.group(1))
        if n:
            return hoje - timedelta(days=n - 1), hoje
    if re.search(r"\bsemana passada\b|\bultima semana\b", t):
        ini = _segunda(hoje) - timedelta(days=7)
        return ini, ini + timedelta(days=6)
    if re.search(r"\b(?:esta|essa|nesta|nessa|desta|dessa)\s+semana\b|\bsemana atual\b", t):
        return _segunda(hoje), hoje
    if re.search(r"\bmes passado\b|\bultimo mes\b|\bmes anterior\b", t):
        ref = hoje.replace(day=1) - timedelta(days=1)
        return ref.replace(day=1), ref
    if re.search(r"\b(?:este|esse|neste|nesse|deste|desse)\s+mes\b|\bmes atual\b|\bdo mes\b", t):
        return hoje.replace(day=1), hoje
    if re.search(r"\b(?:este|esse|neste|nesse|deste|desse)\s+ano\b|\bano atual\b", t):
        return date(hoje.year, 1, 1), hoje
    if re.search(r"\bano passado\b", t):
        return date(hoje.year - 1, 1, 1), date(hoje.year - 1, 12, 31)

    # 4. mês pelo nome: "outubro", "de outubro de 2025"
    m = re.search(r"\b(" + "|".join(k for k in MESES if len(k) > 3) + r")\b(?:\s+de\s+(\d{4}))?", t)
    if m:
        mes = MESES[m.group(1)]
        ano = int(m.group(2)) if m.group(2) else _ano_padrao(mes, hoje)
        fim = _fim_do_mes(ano, mes)
        return date(ano, mes, 1), min(fim, hoje) if (ano, mes) == (hoje.year, hoje.month) else fim
    return None


def formato_de(exemplo):
    """Como a data foi digitada na gravação: '01/10/2026' -> '%d/%m/%Y'; '01102026' -> '%d%m%Y'."""
    e = (exemplo or "").strip()
    if re.fullmatch(r"\d{2}/\d{2}/\d{4}", e):
        return "%d/%m/%Y"
    if re.fullmatch(r"\d{2}/\d{2}/\d{2}", e):
        return "%d/%m/%y"
    if re.fullmatch(r"\d{8}", e):
        return "%d%m%Y"
    if re.fullmatch(r"\d{6}", e):
        return "%d%m%y"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", e):
        return "%Y-%m-%d"
    return None


def parece_data(texto):
    """Texto digitado que é uma data válida (para a skill virar 'campo de data')."""
    f = formato_de(texto)
    if not f:
        return False
    from datetime import datetime
    try:
        d = datetime.strptime(texto.strip(), f)
    except ValueError:
        return False
    return 1990 <= d.year <= 2100


def papel(rotulo, ordem):
    """'Da Data?' / 'De Emissão' -> 'inicio'; 'Até a Data?' / 'Data Final' -> 'fim'. Sem pista: pela ordem."""
    r = _norm(rotulo)
    if re.search(r"\b(ate|final|fim|termino)\b", r):
        return "fim"
    if re.search(r"\b(de|da|do|inicial|inicio|a partir)\b", r):
        return "inicio"
    return "inicio" if ordem == 0 else "fim"


def falar(d):
    return f"{d.day} de {[k for k, v in MESES.items() if v == d.month and len(k) > 3][0]} de {d.year}"
