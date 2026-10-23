"""
GHOST - Perguntas sobre planilhas (Excel/CSV), somente leitura.

"Quanto produzimos ontem na planilha de produção?", "qual produto mais vendeu em outubro?"
A IA NÃO recebe a planilha inteira: ela vê só a estrutura (nomes das colunas e
3 linhas de exemplo) e escolhe a operação (filtrar, agrupar, somar...). O cálculo
é feito aqui no PC, com pandas, e só o resultado (até 20 linhas) volta para a IA.
Nenhum arquivo é alterado.

Pastas pesquisadas: "pastas_planilhas" em dados/preferencias.json (padrão: Documentos,
Área de Trabalho e Downloads). Pastas da rede podem ser incluídas lá, ex.:
  "pastas_planilhas": ["C:\\\\Users\\\\TI-Ivan\\\\Documents", "\\\\\\\\SERVIDOR\\\\PCP"]
Google Planilhas: baixe como .xlsx (Arquivo > Fazer download) para uma dessas pastas.
"""
import difflib
import os
import re
import time
import unicodedata

import pandas as pd

from ghost.nucleo import preferencias

EXTENSOES = (".xlsx", ".xlsm", ".xls", ".csv")
PROFUNDIDADE = 4
MAX_LINHAS_RESULTADO = 20
_indice = {"t": 0, "arquivos": []}


def _normalizar(t):
    t = unicodedata.normalize("NFD", ("" if t is None else str(t)).lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", t)).strip()


def pastas():
    casa = os.path.expanduser("~")
    padrao = [os.path.join(casa, p) for p in ("Documents", "Desktop", "Downloads", "OneDrive")]
    return [p for p in preferencias.carregar().get("pastas_planilhas", padrao) if os.path.isdir(p)]


def _indexar():
    if time.time() - _indice["t"] < 600 and _indice["arquivos"]:
        return _indice["arquivos"]
    achados = []
    for raiz in pastas():
        base = raiz.rstrip("\\/").count(os.sep)
        for pasta, subpastas, arquivos in os.walk(raiz):
            if pasta.count(os.sep) - base >= PROFUNDIDADE:
                subpastas[:] = []
            subpastas[:] = [s for s in subpastas if not s.startswith((".", "$")) and s.lower() != "node_modules"]
            for a in arquivos:
                if a.lower().endswith(EXTENSOES) and not a.startswith("~$"):
                    achados.append(os.path.join(pasta, a))
    _indice.update(t=time.time(), arquivos=achados)
    return achados


VAZIAS = {"planilha", "planilhas", "arquivo", "excel", "tabela", "de", "da", "do", "das", "dos", "a", "o", "na", "no"}


def _palavras(t):
    return [p for p in _normalizar(t).split() if p not in VAZIAS]


def encontrar(nome):
    """Arquivo mais parecido com o nome falado. Compara pelo radical das palavras
    ('planilha de produção' -> 'Producao Outubro.xlsx'); empate: o mais recente."""
    alvo = _palavras(nome)
    if not alvo:
        return None
    melhores = []
    for caminho in _indexar():
        nome_arq = _palavras(os.path.splitext(os.path.basename(caminho))[0])
        achadas = sum(1 for a in alvo if any(n.startswith(a[:5]) or a.startswith(n[:5]) for n in nome_arq if len(n) > 2))
        cobertura = achadas / len(alvo)
        semelhanca = difflib.SequenceMatcher(None, " ".join(alvo), " ".join(nome_arq)).ratio()
        try:
            modificado = os.path.getmtime(caminho)
        except OSError:                      # apagado/movido depois da indexação, ou rede fora
            continue
        melhores.append((round(cobertura, 2), round(semelhanca, 2), modificado, caminho))
    melhores.sort(reverse=True)
    if melhores and (melhores[0][0] >= 0.5 or melhores[0][1] >= 0.7):
        return melhores[0][3]
    return None


def _codificacao(caminho):
    """CSV salvo pelo Excel brasileiro costuma ser cp1252; o resto, UTF-8."""
    with open(caminho, "rb") as f:
        amostra = f.read(1_000_000)
    try:
        amostra.decode("utf-8-sig")
        return "utf-8-sig"
    except UnicodeDecodeError as e:
        cortado = len(amostra) == 1_000_000 and e.reason == "unexpected end of data"   # amostra cortou um caractere
        return "utf-8-sig" if cortado else "cp1252"


def _ler(caminho, aba=None, linha_cabecalho=0):
    if caminho.lower().endswith(".csv"):
        cod = _codificacao(caminho)
        df = None
        for sep, decimal, milhar in ((";", ",", "."), (",", ".", None), ("\t", ",", ".")):
            df = pd.read_csv(caminho, sep=sep, header=linha_cabecalho, encoding=cod, encoding_errors="replace",
                             decimal=decimal, thousands=milhar, on_bad_lines="skip")
            if df.shape[1] > 1:
                break
        df.columns = [str(c).strip() for c in df.columns]
        return df
    df = pd.read_excel(caminho, sheet_name=aba or 0, header=linha_cabecalho)
    df.columns = [str(c).strip() for c in df.columns]
    return df


def estrutura(nome, aba=None):
    caminho = encontrar(nome)
    if not caminho:
        return f"Nenhuma planilha parecida com '{nome}' nas pastas: {', '.join(pastas())}."
    abas = [] if caminho.lower().endswith(".csv") else pd.ExcelFile(caminho).sheet_names
    df = _ler(caminho, aba)
    tipos = ", ".join(f"{c} ({'número' if pd.api.types.is_numeric_dtype(df[c]) else 'data' if pd.api.types.is_datetime64_any_dtype(df[c]) else 'texto'})"
                      for c in df.columns[:40])
    return (f"Arquivo: {os.path.basename(caminho)} | modificado {time.strftime('%d/%m/%Y %H:%M', time.localtime(os.path.getmtime(caminho)))}\n"
            f"Abas: {abas or '-'} | aba lida: {aba or (abas[0] if abas else '-')} | {len(df)} linhas\n"
            f"Colunas: {tipos}\nExemplo:\n{df.head(3).to_string(max_colwidth=25)}")


def _datas(serie):
    """Datas de texto (22/10/2026, 2026-10-22), datas do Excel e números de série do Excel (46317)."""
    if pd.api.types.is_datetime64_any_dtype(serie):
        return serie
    if pd.api.types.is_numeric_dtype(serie):
        n = pd.to_numeric(serie, errors="coerce")
        if n.notna().any() and n.between(20000, 80000).mean() > 0.6:   # 1954..2118
            return pd.to_datetime(n, unit="D", origin="1899-12-30", errors="coerce")
        return pd.Series(pd.NaT, index=serie.index)
    iso = serie.astype(str).str.match(r"\s*\d{4}-\d{2}-\d{2}")
    return pd.to_datetime(serie.where(~iso), errors="coerce", dayfirst=True).fillna(
        pd.to_datetime(serie.where(iso), errors="coerce"))


def _numero(v):
    """'1.234,5' / '1234.5' / '12' -> float; None se não for número."""
    t = str(v).strip().replace(" ", "")
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+(,\d+)?|-?\d+,\d+", t):
        t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def calcular(nome, aba=None, filtros=None, agrupar_por=None, coluna_valor=None, operacao="soma",
             ordenar="desc", limite=10):
    """filtros: [{"coluna", "operador": = != contem > >= < <= entre, "valor"}]; datas em AAAA-MM-DD,
    'entre' usa "AAAA-MM-DD|AAAA-MM-DD"."""
    caminho = encontrar(nome)
    if not caminho:
        return f"Nenhuma planilha parecida com '{nome}'."
    df = _ler(caminho, aba)
    colunas = {_normalizar(c): c for c in df.columns}

    def col(c):
        real = colunas.get(_normalizar(c)) or next((v for k, v in colunas.items() if _normalizar(c) in k), None)
        if real is None:
            raise ValueError(f"coluna '{c}' não existe. Colunas: {list(df.columns)}")
        return real

    def _iso(v):  # aceita 22/10/2026 ou 2026-10-22
        m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", v.strip())
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else v.strip()

    for f in filtros or []:
        c, op = col(f["coluna"]), f.get("operador", "=")
        if op not in ("=", "!=", "contem", ">", ">=", "<", "<=", "entre"):
            raise ValueError(f"operador '{op}' inválido (use = != contem > >= < <= entre)")
        v = "|".join(_iso(p) for p in str(f.get("valor", "")).split("|"))
        datas = _datas(df[c])
        eh_data = datas.notna().mean() > 0.6 and re.match(r"\d{4}-\d{2}-\d{2}", v)
        if op == "entre":
            if v.count("|") != 1:
                raise ValueError("'entre' precisa de dois valores: início|fim")
            a, b = v.split("|")
            serie = datas if eh_data else pd.to_numeric(df[c], errors="coerce")
            if eh_data:
                ini, fim = pd.Timestamp(a), pd.Timestamp(b) + pd.Timedelta(days=1)
            else:
                ini, fim = _numero(a), _numero(b)
                if ini is None or fim is None:
                    raise ValueError(f"'{v}' não são dois números")
            df = df[(serie >= ini) & (serie < fim)] if eh_data else df[(serie >= ini) & (serie <= fim)]
        elif eh_data:
            alvo = pd.Timestamp(v)
            d = datas.dt.normalize()
            df = df[{"=": d == alvo, "!=": d != alvo, ">": d > alvo, ">=": d >= alvo, "<": d < alvo, "<=": d <= alvo}[op]]
        elif op == "contem":
            df = df[df[c].astype(str).map(_normalizar).str.contains(_normalizar(v), na=False)]
        elif op in ("=", "!="):
            num = _numero(v)
            if num is not None and pd.api.types.is_numeric_dtype(df[c]):
                igual = pd.to_numeric(df[c], errors="coerce").sub(num).abs() < 1e-9    # 10 == 10.0
            else:
                igual = df[c].astype(str).map(_normalizar) == _normalizar(v)
            df = df[igual if op == "=" else ~igual]
        else:
            num = _numero(v)
            if num is None:
                raise ValueError(f"'{v}' não é número para comparar com {op}")
            n = pd.to_numeric(df[c], errors="coerce")
            df = df[{">": n > num, ">=": n >= num, "<": n < num, "<=": n <= num}[op]]

    if not len(df):
        return "Nenhuma linha atende aos filtros."
    funcs = {"soma": "sum", "media": "mean", "contagem": "count", "max": "max", "min": "min"}
    if operacao == "contagem" and not coluna_valor:
        coluna_valor = df.columns[0]
    valores = pd.to_numeric(df[col(coluna_valor)], errors="coerce") if coluna_valor and operacao != "contagem" \
        else df[col(coluna_valor)] if coluna_valor else None

    if operacao not in funcs:
        raise ValueError(f"operação '{operacao}' inválida (use {', '.join(funcs)})")
    if agrupar_por:
        if valores is None:
            raise ValueError("para agrupar, informe coluna_valor (a coluna a somar/contar)")
        grupos = [col(g) for g in (agrupar_por if isinstance(agrupar_por, list) else [agrupar_por])]
        res = (valores.groupby([df[g] for g in grupos]).agg(funcs[operacao])
               .sort_values(ascending=(ordenar == "asc")).head(min(int(limite), MAX_LINHAS_RESULTADO)))
        return f"{operacao} de {coluna_valor} por {', '.join(grupos)} ({len(df)} linhas filtradas):\n{res.to_string()}"
    if valores is not None and operacao != "contagem" and valores.notna().sum() == 0:
        return f"A coluna {coluna_valor} não tem números nas {len(df)} linhas filtradas."
    if valores is not None and operacao in ("max", "min"):
        # devolve a LINHA inteira do maior/menor valor (assim aparece o produto, a data etc.)
        idx = valores.idxmax() if operacao == "max" else valores.idxmin()
        return (f"{operacao} de {coluna_valor} = {valores[idx]} na linha:\n"
                f"{df.loc[[idx]].to_string(max_colwidth=30)}\n(arquivo {os.path.basename(caminho)})")
    if valores is not None:
        r = getattr(valores, funcs[operacao])()
        r = round(float(r), 2) if operacao != "contagem" else int(r)
        return f"{operacao} de {coluna_valor} = {r} ({len(df)} linhas filtradas, arquivo {os.path.basename(caminho)})"
    return f"{len(df)} linhas filtradas:\n{df.head(MAX_LINHAS_RESULTADO).to_string(max_colwidth=25)}"
