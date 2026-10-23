"""
GHOST - Perguntas sobre planilhas (Excel/CSV), somente leitura.

"Quanto produzimos ontem na planilha de produção?", "qual produto mais vendeu em outubro?"
A IA NÃO recebe a planilha inteira: ela vê só a estrutura (nomes das colunas e
3 linhas de exemplo) e escolhe a operação (filtrar, agrupar, somar...). O cálculo
é feito aqui no PC, com pandas, e só o resultado (até 20 linhas) volta para a IA.
Nenhum arquivo é alterado.

Pastas pesquisadas: "pastas_planilhas" em preferencias.json (padrão: Documentos,
Área de Trabalho e Downloads). Pastas da rede podem ser incluídas lá, ex.:
  "pastas_planilhas": ["C:\\\\Users\\\\TI-Ivan\\\\Documents", "\\\\\\\\SERVIDOR\\\\PCP"]
Google Planilhas: baixe como .xlsx (Arquivo > Fazer download) para uma dessas pastas.
"""
import os
import re
import time
import difflib
import unicodedata

import pandas as pd

import preferencias

EXTENSOES = (".xlsx", ".xlsm", ".xls", ".csv")
PROFUNDIDADE = 4
MAX_LINHAS_RESULTADO = 20
_indice = {"t": 0, "arquivos": []}


def _normalizar(t):
    t = unicodedata.normalize("NFD", (t or "").lower())
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
        melhores.append((round(cobertura, 2), round(semelhanca, 2), os.path.getmtime(caminho), caminho))
    melhores.sort(reverse=True)
    if melhores and (melhores[0][0] >= 0.5 or melhores[0][1] >= 0.7):
        return melhores[0][3]
    return None


def _ler(caminho, aba=None, linha_cabecalho=0):
    if caminho.lower().endswith(".csv"):
        for sep in (";", ","):
            df = pd.read_csv(caminho, sep=sep, header=linha_cabecalho, encoding="utf-8-sig", encoding_errors="replace")
            if df.shape[1] > 1:
                return df
        return df
    return pd.read_excel(caminho, sheet_name=aba or 0, header=linha_cabecalho)


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
    return pd.to_datetime(serie, errors="coerce", dayfirst=True)


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
        v = "|".join(_iso(p) for p in str(f.get("valor", "")).split("|"))
        datas = _datas(df[c])
        eh_data = datas.notna().mean() > 0.6 and re.match(r"\d{4}-\d{2}-\d{2}", v)
        if op == "entre":
            a, b = v.split("|")
            serie = datas if eh_data else pd.to_numeric(df[c], errors="coerce")
            ini, fim = (pd.Timestamp(a), pd.Timestamp(b) + pd.Timedelta(days=1)) if eh_data else (float(a), float(b))
            df = df[(serie >= ini) & (serie < fim)] if eh_data else df[(serie >= ini) & (serie <= fim)]
        elif eh_data:
            alvo = pd.Timestamp(v)
            d = datas.dt.normalize()
            df = df[{"=": d == alvo, "!=": d != alvo, ">": d > alvo, ">=": d >= alvo, "<": d < alvo, "<=": d <= alvo}[op]]
        elif op == "contem":
            df = df[df[c].astype(str).map(_normalizar).str.contains(_normalizar(v), na=False)]
        elif op in ("=", "!="):
            igual = df[c].astype(str).map(_normalizar) == _normalizar(v)
            df = df[igual if op == "=" else ~igual]
        else:
            n = pd.to_numeric(df[c], errors="coerce")
            df = df[{">": n > float(v), ">=": n >= float(v), "<": n < float(v), "<=": n <= float(v)}[op]]

    if not len(df):
        return "Nenhuma linha atende aos filtros."
    funcs = {"soma": "sum", "media": "mean", "contagem": "count", "max": "max", "min": "min"}
    if operacao == "contagem" and not coluna_valor:
        coluna_valor = df.columns[0]
    valores = pd.to_numeric(df[col(coluna_valor)], errors="coerce") if coluna_valor and operacao != "contagem" \
        else df[col(coluna_valor)] if coluna_valor else None

    if agrupar_por:
        grupos = [col(g) for g in (agrupar_por if isinstance(agrupar_por, list) else [agrupar_por])]
        res = (valores.groupby([df[g] for g in grupos]).agg(funcs.get(operacao, "sum"))
               .sort_values(ascending=(ordenar == "asc")).head(min(int(limite), MAX_LINHAS_RESULTADO)))
        return f"{operacao} de {coluna_valor} por {', '.join(grupos)} ({len(df)} linhas filtradas):\n{res.to_string()}"
    if valores is not None and operacao in ("max", "min"):
        # devolve a LINHA inteira do maior/menor valor (assim aparece o produto, a data etc.)
        idx = valores.idxmax() if operacao == "max" else valores.idxmin()
        return (f"{operacao} de {coluna_valor} = {valores[idx]} na linha:\n"
                f"{df.loc[[idx]].to_string(max_colwidth=30)}\n(arquivo {os.path.basename(caminho)})")
    if valores is not None:
        r = getattr(valores, funcs.get(operacao, "sum"))()
        r = round(float(r), 2) if operacao != "contagem" else int(r)
        return f"{operacao} de {coluna_valor} = {r} ({len(df)} linhas filtradas, arquivo {os.path.basename(caminho)})"
    return f"{len(df)} linhas filtradas:\n{df.head(MAX_LINHAS_RESULTADO).to_string(max_colwidth=25)}"
