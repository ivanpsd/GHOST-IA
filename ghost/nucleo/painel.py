"""
GHOST - Painel (a "tela de programa" do Ghost) com todos os indicadores.

Como funciona:
- O Ghost serve uma página local (só neste PC: http://127.0.0.1) com os indicadores em JSON.
- A janela é o Microsoft Edge em "modo aplicativo" (sem abas nem barra de endereço), então
  parece um programa próprio e não precisa de nenhuma biblioteca a mais.
- Exportar: botão "Exportar" na janela, ou por voz ("Ghost, exportar indicadores").
  Gera um Excel em Documentos\\Ghost\\Relatorios\\ com Resumo, Histórico (1 linha por minuto) e Eventos.

Por voz: "Ghost, abrir painel" / "fechar painel" / "exportar indicadores".
O resto do Ghost só AVISA o painel do que acontece (estado(), fala(), contar(), medir(), evento());
nada aqui pode derrubar o Ghost: toda leitura é protegida.
"""
import ctypes
import json
import os
import secrets
import shutil
import subprocess
import threading
import time
from collections import deque
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from ghost.nucleo import caminhos, preferencias

PASTA_WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "painel_web")
PASTA_EXPORTAR = os.path.join(os.path.expanduser("~"), "Documents", "Ghost", "Relatorios")
PORTA = 8765                      # se estiver ocupada, usa uma porta livre qualquer
COLETA_S = 5                      # leitura de CPU/RAM/disco/bateria
MEMORIA_S = 600                   # registra no log a memória do próprio Ghost (para achar vazamento)
TAMANHO_JANELA = (1280, 800)

_trava = threading.Lock()
_token = secrets.token_urlsafe(16)    # outra página aberta no navegador não consegue chamar o painel
_servidor = None
_janela = None                        # processo do Edge
_falar = None
_inicio = time.time()

_estado = {"nome": "espera", "texto": "", "desde": time.time()}
_falas = {"voce": "", "ghost": "", "voce_t": 0.0, "ghost_t": 0.0}
_ia = {"modelo": "", "ultima_t": 0.0}
_medidas = {"transcricao": deque(maxlen=20), "primeira_frase": deque(maxlen=20)}
_contadores = {"dia": date.today().isoformat()}
_eventos = deque(maxlen=200)
_amostras = deque(maxlen=720)         # a cada COLETA_S: ~1 h para os mini-gráficos
_historico = deque(maxlen=1440)       # 1 por minuto: 24 h para a exportação
_sistema = {"cpu": None, "ram": None, "disco_livre_gb": None, "disco_livre_pct": None,
            "bateria": None, "na_tomada": None, "internet": None, "latencia_ms": None}
_requisicoes = {"n": 0, "limite": 0}
_celular = deque(maxlen=60)           # conversa do app do celular
_imagens = {}                         # id -> JPEG das imagens mandadas ao celular (só em memória)
MAX_IMAGENS = 8
PASTA_DEMO = os.path.join(os.path.expanduser("~"), "Documents", "Ghost", "Demonstracao")
ESTATICOS = {"nucleo.js": "text/javascript; charset=utf-8", "icone-192.png": "image/png", "icone-512.png": "image/png"}


# =============================================================
# 1. O QUE O RESTO DO GHOST CHAMA (qualquer thread, nunca levanta erro)
# =============================================================
def estado(nome, texto=""):
    with _trava:
        if nome != _estado["nome"]:
            _estado["desde"] = time.time()
        _estado.update(nome=nome, texto=(texto or "")[:200])


def fala(quem, texto):
    """quem: 'voce' ou 'ghost'."""
    with _trava:
        _falas[quem], _falas[quem + "_t"] = (texto or "")[:400], time.time()


def ia(modelo):
    with _trava:
        _ia.update(modelo=modelo, ultima_t=time.time())


def requisicoes(n, limite):
    with _trava:
        _requisicoes.update(n=n, limite=limite)


def medir(nome, segundos):
    with _trava:
        if nome in _medidas:
            _medidas[nome].append(round(float(segundos), 2))


def contar(chave, n=1):
    """Contadores do dia: comandos, comandos_locais, falsos_alarmes, erros, nao_entendi..."""
    with _trava:
        hoje = date.today().isoformat()
        if _contadores.get("dia") != hoje:
            _contadores.clear()
            _contadores["dia"] = hoje
        _contadores[chave] = _contadores.get(chave, 0) + n


def mensagem_celular(quem, texto):
    """Conversa mostrada no app do celular. quem: 'voce' ou 'ghost'."""
    with _trava:
        _celular.append({"t": time.time(), "quem": quem, "texto": (texto or "")[:2000]})


def imagem_celular(img, legenda):
    """Manda uma imagem (PIL) para a conversa do app do celular. Fica só na memória (últimas MAX_IMAGENS)."""
    import io
    img = img.convert("RGB")
    if img.width > 1920:
        img = img.resize((1920, round(img.height * 1920 / img.width)))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    ident = secrets.token_hex(8)
    with _trava:
        _imagens[ident] = buf.getvalue()
        for velho in list(_imagens)[:-MAX_IMAGENS]:
            del _imagens[velho]
        _celular.append({"t": time.time(), "quem": "ghost", "texto": (legenda or "")[:300], "imagem": ident})
    return ident


def imagem(ident):
    with _trava:
        return _imagens.get(ident)


def evento(texto, tipo="info"):
    """tipo: info, acao, alerta, erro."""
    with _trava:
        _eventos.append({"t": time.time(), "tipo": tipo, "texto": (texto or "")[:160]})


# =============================================================
# 2. LEITURAS DO SISTEMA
# =============================================================
class _Tempos(ctypes.Structure):
    _fields_ = [("baixo", ctypes.c_ulong), ("alto", ctypes.c_ulong)]


def _tempos_cpu():
    ocioso, kernel, usuario = _Tempos(), _Tempos(), _Tempos()
    ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(ocioso), ctypes.byref(kernel), ctypes.byref(usuario))
    v = [(t.alto << 32) | t.baixo for t in (ocioso, kernel, usuario)]
    return v[0], v[1] + v[2]          # (ocioso, total): kernel já inclui o ocioso


def _coletar():
    from ghost.nucleo import sistema
    from ghost.servicos import alertas, rede
    anterior = None
    ult_minuto = ult_memoria = 0.0
    while True:
        try:
            leitura = {}
            if os.name == "nt":
                agora_cpu = _tempos_cpu()
                if anterior:
                    d_ocioso, d_total = agora_cpu[0] - anterior[0], agora_cpu[1] - anterior[1]
                    leitura["cpu"] = round(100 * (1 - d_ocioso / d_total)) if d_total > 0 else None
                anterior = agora_cpu
                leitura["ram"] = alertas._memoria_pct()
                gb, pct = alertas._disco_c()
                leitura["disco_livre_gb"], leitura["disco_livre_pct"] = round(gb, 1), round(pct)
                bat, tomada = alertas._bateria()
                leitura["bateria"], leitura["na_tomada"] = bat, tomada
            ultima = rede.ultima_internet()                 # o vigia da rede já mede a cada minuto: não mede de novo
            if ultima:
                leitura["latencia_ms"], leitura["internet"] = ultima.get("net_ms"), ultima.get("net_ms") is not None
            if time.time() - ult_memoria >= MEMORIA_S:      # memória do próprio Ghost: mostra se há vazamento
                ult_memoria = time.time()
                uso, reservada = sistema.memoria_ghost_mb()
                leitura["ghost_mb"] = uso
                if uso is not None:
                    print(f"\n[MEMÓRIA]: Ghost usando {uso} MB (reservado {reservada} MB).")
            with _trava:
                _sistema.update(leitura)
                amostra = {"t": time.time(), "cpu": _sistema["cpu"], "ram": _sistema["ram"],
                           "latencia_ms": _sistema["latencia_ms"]}
                _amostras.append(amostra)
                if time.time() - ult_minuto >= 60:
                    ult_minuto = time.time()
                    _historico.append({**_sistema, "t": time.time(), "estado": _estado["nome"],
                                       "requisicoes_ia": _requisicoes["n"],
                                       "comandos": _contadores.get("comandos", 0)})
        except Exception as e:
            print(f"\n[PAINEL]: leitura do sistema falhou ({e!r}).")
        time.sleep(COLETA_S)


# =============================================================
# 3. FOTO DO MOMENTO (o JSON que a janela lê a cada segundo)
# =============================================================
def _seguro(funcao, padrao=None):
    try:
        return funcao()
    except Exception:
        return padrao


def _modo():
    from ghost.voz import ativacao
    return ativacao.modo()


def _ativacao():
    return {"ligada": False, "treinada": False, "f9": True}       # ativação só pelo F9 (palavra "Ghost" retirada)


def _lembretes():
    from ghost.servicos import lembretes
    itens = []
    for item in lembretes._carregar():
        d = lembretes._data(item)
        if d and d >= datetime.now():
            itens.append({"quando": d.strftime("%d/%m %H:%M"), "ordem": d.isoformat(), "texto": item.get("texto", "")})
    return sorted(itens, key=lambda x: x["ordem"])[:4]


def _tarefas():
    from ghost.ia import tarefas
    return [{"id": t["id"], "descricao": t["descricao"][:80], "status": t["status"],
             "minutos": int((time.time() - t["inicio"]) / 60)} for t in list(tarefas._tarefas)[-4:]][::-1]


def _notificacoes():
    from ghost.servicos import notificacoes
    return [{"hora": datetime.fromtimestamp(n["t"]).strftime("%H:%M"), "app": n["app"],
             "quem": (n["textos"] or [""])[0][:40]} for n in list(notificacoes._recentes)[-4:]][::-1]


def _memoria():
    from ghost.ia import memoria, memoria_longa, skills
    longa = memoria_longa._itens
    return {"fatos": len(memoria.carregar_fatos()), "skills": len(skills.carregar()),
            "conversas": len(longa) if longa is not None else None}


def _rotina():
    from ghost.servicos import rotina
    hoje = datetime.now().strftime("%Y-%m-%d")
    tempos = {}
    for e in rotina._eventos()[-2000:]:
        if e["inicio"].startswith(hoje) and e["app"] != "ausente":
            nome = e["app"].replace(".exe", "").replace(".EXE", "")
            tempos[nome] = tempos.get(nome, 0) + e["segundos"]
    return {"ativa": rotina.observando,
            "top": [{"app": a, "minutos": s // 60} for a, s in sorted(tempos.items(), key=lambda x: -x[1])[:5]]}


def _clima():
    from ghost.servicos import resumo
    agora = time.time()
    if agora - _clima_cache["t"] > 1800:
        _clima_cache.update(t=agora, texto=resumo.clima())
    return _clima_cache["texto"]


_clima_cache = {"t": 0.0, "texto": ""}


def foto():
    """Tudo o que a janela mostra (e o que vai para a exportação)."""
    with _trava:
        base = {
            "agora": time.time(), "inicio": _inicio,
            "estado": dict(_estado), "falas": dict(_falas), "ia": dict(_ia),
            "requisicoes": dict(_requisicoes), "contadores": dict(_contadores),
            "medidas": {k: list(v) for k, v in _medidas.items()},
            "sistema": dict(_sistema),
            "serie": [{"cpu": a["cpu"], "ram": a["ram"], "latencia_ms": a["latencia_ms"]} for a in list(_amostras)[-120:]],
            "eventos": list(_eventos)[-14:][::-1],
            "celular": list(_celular),
        }
    base.update({
        "modo": _seguro(_modo, "normal"),
        "ativacao": _seguro(_ativacao, {}),
        "personalidade": _seguro(lambda: preferencias.carregar().get("personalidade", "jarvis"), "jarvis"),
        "lembretes": _seguro(_lembretes, []),
        "tarefas": _seguro(_tarefas, []),
        "notificacoes": _seguro(_notificacoes, []),
        "memoria": _seguro(_memoria, {}),
        "rotina": _seguro(_rotina, {}),
        "clima": _seguro(_clima, ""),
    })
    return base


# =============================================================
# 4. EXPORTAÇÃO (Excel)
# =============================================================
def exportar():
    """Gera o Excel com os indicadores. Devolve o caminho do arquivo."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    f = foto()
    with _trava:
        historico = list(_historico)
        eventos = list(_eventos)
    os.makedirs(PASTA_EXPORTAR, exist_ok=True)
    caminho = os.path.join(PASTA_EXPORTAR, f"Indicadores_Ghost_{datetime.now():%Y-%m-%d_%H%M}.xlsx")

    cabecalho = Font(bold=True, color="FFF4E6")
    fundo = PatternFill("solid", fgColor="7A2E0E")
    wb = Workbook()

    def aba(ws, titulo, colunas, linhas, larguras):
        ws.title = titulo
        ws.append(colunas)
        for c in ws[1]:
            c.font, c.fill, c.alignment = cabecalho, fundo, Alignment(vertical="center")
        for linha in linhas:
            ws.append(linha)
        for i, w in enumerate(larguras):
            ws.column_dimensions[chr(65 + i)].width = w
        ws.freeze_panes = "A2"

    s, c, m = f["sistema"], f["contadores"], f["memoria"] or {}
    media = lambda xs: round(sum(xs) / len(xs), 2) if xs else None  # noqa: E731
    resumo = [
        ("Gerado em", datetime.now().strftime("%d/%m/%Y %H:%M:%S")),
        ("Ligado há (min)", int((time.time() - f["inicio"]) / 60)),
        ("Estado", f["estado"]["nome"]), ("Modo", f["modo"]), ("Personalidade", f["personalidade"]),
        ("Ativação por voz", "ligada" if (f["ativacao"] or {}).get("ligada") else "desligada"),
        ("Detector treinado na sua voz", "sim" if (f["ativacao"] or {}).get("treinada") else "não"),
        ("CPU (%)", s["cpu"]), ("Memória RAM (%)", s["ram"]),
        ("Disco C livre (GB)", s["disco_livre_gb"]), ("Disco C livre (%)", s["disco_livre_pct"]),
        ("Bateria (%)", s["bateria"]), ("Na tomada", s["na_tomada"]),
        ("Internet", "ok" if s["internet"] else "fora" if s["internet"] is False else "?"),
        ("Latência até a IA (ms)", s["latencia_ms"]),
        ("Modelo de IA em uso", f["ia"]["modelo"]),
        ("Requisições à IA hoje", f["requisicoes"]["n"]), ("Limite diário de alerta", f["requisicoes"]["limite"]),
        ("Voz → texto, média (s)", media(f["medidas"]["transcricao"])),
        ("1ª frase da IA, média (s)", media(f["medidas"]["primeira_frase"])),
        ("Comandos hoje", c.get("comandos", 0)), ("Comandos locais (sem IA)", c.get("comandos_locais", 0)),
        ("Alarmes falsos evitados", c.get("falsos_alarmes", 0)), ("Não entendi", c.get("nao_entendi", 0)),
        ("Erros", c.get("erros", 0)),
        ("Fatos aprendidos", m.get("fatos")), ("Skills", m.get("skills")), ("Conversas na memória longa", m.get("conversas")),
        ("Clima", f["clima"]),
    ]
    aba(wb.active, "Resumo", ["Indicador", "Valor"], resumo, [34, 60])
    aba(wb.create_sheet(), "Histórico",
        ["Data e hora", "Estado", "CPU %", "RAM %", "Disco livre GB", "Bateria %", "Internet", "Latência ms",
         "Requisições IA (acum.)", "Comandos (acum.)"],
        [(datetime.fromtimestamp(h["t"]), h.get("estado"), h.get("cpu"), h.get("ram"), h.get("disco_livre_gb"),
          h.get("bateria"), "ok" if h.get("internet") else "fora" if h.get("internet") is False else "",
          h.get("latencia_ms"), h.get("requisicoes_ia"), h.get("comandos")) for h in historico],
        [19, 12, 8, 8, 14, 10, 9, 12, 20, 16])
    aba(wb.create_sheet(), "Eventos", ["Data e hora", "Tipo", "Evento"],
        [(datetime.fromtimestamp(e["t"]), e["tipo"], e["texto"]) for e in eventos], [19, 9, 90])
    aba(wb.create_sheet(), "Rotina de hoje", ["Programa", "Minutos"],
        [(r["app"], r["minutos"]) for r in (f["rotina"] or {}).get("top", [])], [30, 10])
    for ws in wb.worksheets:
        for linha in ws.iter_rows(min_row=2):
            for cel in linha:
                if isinstance(cel.value, datetime):
                    cel.number_format = "dd/mm/yyyy hh:mm"
    tmp = caminho + ".tmp"
    wb.save(tmp)
    os.replace(tmp, caminho)
    evento(f"Indicadores exportados: {os.path.basename(caminho)}", "acao")
    return caminho


# =============================================================
# 5. DEMONSTRAÇÃO (o app do celular fica em nucleo/celular.py)
# =============================================================
def criar_demonstracao(abrir=True):
    """Gera a demonstração (dados de exemplo) em Documentos\\Ghost\\Demonstracao e abre a janela.
    São arquivos soltos: dá para copiar num pendrive ou mandar para alguém ver."""
    os.makedirs(PASTA_DEMO, exist_ok=True)
    with open(os.path.join(PASTA_WEB, "nucleo.js"), encoding="utf-8") as f:
        nucleo_js = f.read()
    for origem, destino, envolver in (("index.html", "Painel_Ghost.html", True), ("celular.html", "celular.html", False)):
        with open(os.path.join(PASTA_WEB, origem), encoding="utf-8") as f:
            html = f.read().replace('<script src="nucleo.js"></script>', f"<script>\n{nucleo_js}\n</script>")
        if envolver:
            html = ('<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
                    '<meta name="viewport" content="width=device-width, initial-scale=1"></head><body>' + html + "</body></html>")
        with open(os.path.join(PASTA_DEMO, destino), "w", encoding="utf-8") as f:
            f.write(html)
    for icone in ("icone-192.png", "icone-512.png"):
        shutil.copy2(os.path.join(PASTA_WEB, icone), os.path.join(PASTA_DEMO, icone))
    caminho = os.path.join(PASTA_DEMO, "Painel_Ghost.html")
    evento("Demonstração do painel criada", "acao")
    if abrir:
        exe = _edge()
        url = "file:///" + caminho.replace("\\", "/")
        if exe:
            largura, altura = TAMANHO_JANELA
            subprocess.Popen([exe, f"--app={url}", f"--user-data-dir={caminhos.dado('painel_janela')}",
                              f"--window-size={largura},{altura}", "--no-first-run", "--no-default-browser-check"])
        else:
            import webbrowser
            webbrowser.open(url)
    return caminho


# =============================================================
# 6. SERVIDOR LOCAL + JANELA
# =============================================================
class _Rotas(BaseHTTPRequestHandler):
    """Servidor do PC: só 127.0.0.1 e só com a chave desta sessão (o celular usa nucleo/celular.py)."""

    def log_message(self, *_):            # sem poluir o ghost.log a cada segundo
        pass

    def _autorizado(self):
        recebido = (parse_qs(urlparse(self.path).query).get("t") or [""])[0]
        return secrets.compare_digest(recebido, _token)

    def _responder(self, codigo, corpo, tipo="application/json; charset=utf-8"):
        dados = corpo if isinstance(corpo, bytes) else json.dumps(corpo, ensure_ascii=False, default=str).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def _arquivo(self, nome):
        with open(os.path.join(PASTA_WEB, nome), "rb") as arq:
            return arq.read()

    def do_GET(self):
        rota = urlparse(self.path).path.lstrip("/")
        if rota in ESTATICOS:                     # arquivos sem nada pessoal: não pedem chave
            return self._responder(200, self._arquivo(rota), ESTATICOS[rota])
        if not self._autorizado():
            return self._responder(403, {"erro": "acesso negado"})
        try:
            if rota in ("", "index.html"):
                corpo = self._arquivo("index.html").replace(b"__GHOST_TOKEN__", _token.encode())
                html = (b'<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
                        b'<meta name="viewport" content="width=device-width, initial-scale=1"></head><body>'
                        + corpo + b"</body></html>")
                return self._responder(200, html, "text/html; charset=utf-8")
            if rota == "estado":
                return self._responder(200, foto())
            if rota == "skill/rascunho":
                from ghost.automacao import demonstracao as demo
                r = demo.rascunho()
                if not r:
                    return self._responder(200, {"rascunho": None, "gravando": demo.gravando()})
                passos = [{"n": i, "texto": demo.descrever(p), "acao": p["acao"], "imagem": bool(p.get("recorte")),
                           "variavel": bool(p.get("variavel")), "segredo": bool(p.get("segredo")),
                           "data": p.get("tipo") == "data"}
                          for i, p in enumerate(r["passos"], 1)]
                return self._responder(200, {"rascunho": {"nome": r["nome"], "gatilho": r["gatilho"], "passos": passos,
                                                          "avisos": demo.avisos(r["passos"])},
                                             "gravando": demo.gravando()})
            if rota == "skill/imagem":
                from ghost.automacao import demonstracao as demo
                r = demo.rascunho()
                n = int((parse_qs(urlparse(self.path).query).get("n") or ["0"])[0])
                if not r or not 1 <= n <= len(r["passos"]) or not r["passos"][n - 1].get("recorte"):
                    return self._responder(404, {"erro": "sem imagem"})
                nome = os.path.basename(r["passos"][n - 1]["recorte"])
                with open(os.path.join(demo.PASTA_RASCUNHO, nome), "rb") as arq:
                    return self._responder(200, arq.read(), "image/png")
            if rota.startswith("hud/"):                # telas de visualização (HUDS + painel_web/hud_<nome>.html)
                partes = rota.split("/")
                nome = partes[1] if len(partes) > 1 else ""
                if nome not in HUDS:
                    return self._responder(404, {"erro": "HUD não existe"})
                if len(partes) == 3 and partes[2] == "dados":
                    return self._responder(200, HUDS[nome][1]())
                html = self._arquivo(f"hud_{nome}.html").replace(b"__GHOST_TOKEN__", _token.encode())
                return self._responder(200, html, "text/html; charset=utf-8")
            if rota == "celular/situacao":
                from ghost.nucleo import celular
                return self._responder(200, celular.situacao())
            return self._responder(404, {"erro": "não encontrado"})
        except Exception as e:
            return self._responder(500, {"erro": str(e)})

    def do_POST(self):
        if not self._autorizado():
            return self._responder(403, {"erro": "acesso negado"})
        rota = urlparse(self.path).path.lstrip("/")
        q = parse_qs(urlparse(self.path).query)
        try:
            if rota == "exportar":
                return self._responder(200, {"arquivo": exportar()})
            if rota == "hud/rede/editar":             # ficha do link neural: só o inventário do Ghost, não a máquina
                from ghost.servicos import rede
                n = int(self.headers.get("Content-Length") or 0)
                j = json.loads(self.rfile.read(min(n, 10_000)) or b"{}") if n else {}
                if j.get("departamento_novo"):
                    return self._responder(200, {"departamentos": rede.definir_departamentos([str(j["departamento_novo"])[:40]])})
                if j.get("departamento_remover"):
                    return self._responder(200, {"departamentos": rede.definir_departamentos(
                        [str(j["departamento_remover"])], remover=True)})
                a = rede.editar(str(j.get("mac") or ""), j.get("campos") or {})
                if a is None:
                    return self._responder(404, {"erro": "aparelho não está no inventário"})
                evento(f"Rede: {rede.nome_exibicao(a)} atualizado", "acao")
                return self._responder(200, {"ok": True})
            if rota == "skill/acao":
                from ghost.automacao import demonstracao as demo
                n = int(self.headers.get("Content-Length") or 0)
                j = json.loads(self.rfile.read(min(n, 10_000)) or b"{}") if n else {}
                acao, k = j.get("acao"), int(j.get("n") or 0)
                if acao == "remover":
                    demo.remover_passo(k)
                elif acao == "variavel":
                    demo.marcar_variavel(k)
                elif acao == "fixo":
                    demo.marcar_variavel(k, ligar=False)
                elif acao == "nome":
                    demo.definir_nome(str(j.get("nome") or ""), str(j.get("gatilho") or "") or None)
                elif acao == "descartar":
                    demo.descartar()
                elif acao == "salvar":
                    if j.get("nome"):
                        demo.definir_nome(str(j["nome"]), str(j.get("gatilho") or "") or None)
                    s = demo.salvar()
                    evento(f"Skill gravada salva: {s['nome']}", "acao")
                    return self._responder(200, {"ok": True, "nome": s["nome"], "gatilho": s["gatilhos"][0]})
                elif acao == "testar":
                    r = demo.rascunho()
                    if not r:
                        return self._responder(400, {"erro": "não há skill gravada"})
                    if not _falar:
                        return self._responder(503, {"erro": "o Ghost ainda está iniciando"})
                    from ghost.automacao import automacoes
                    automacoes.em_segundo_plano(lambda: demo.executar({"nome": "teste", "passos": r["passos"]}, _falar,
                                                                      lambda q: automacoes.perguntar(q, _falar), teste=True))
                else:
                    return self._responder(400, {"erro": "ação desconhecida"})
                return self._responder(200, {"ok": True})
            from ghost.nucleo import celular
            if rota == "celular/ativar":
                return self._responder(200, celular.ativar())
            if rota == "celular/remover":
                celular.remover((q.get("id") or [""])[0])
                return self._responder(200, celular.situacao())
            if rota == "celular/desativar":
                celular.desativar()
                return self._responder(200, celular.situacao())
            return self._responder(404, {"erro": "não encontrado"})
        except Exception as e:
            from ghost.nucleo import celular
            if isinstance(e, celular.ErroCelular):
                return self._responder(400, {"erro": str(e)})
            if isinstance(e, ValueError):            # ex.: "falta o nome" ao salvar a skill
                return self._responder(400, {"erro": str(e)})
            evento(f"Painel: {rota} falhou ({e})", "erro")
            return self._responder(500, {"erro": str(e)})


def endereco():
    return f"http://127.0.0.1:{_servidor.server_address[1]}/?t={_token}" if _servidor else None


def _edge():
    for base in (os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", ""),
                 os.environ.get("LOCALAPPDATA", "")):
        exe = os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe")
        if base and os.path.exists(exe):
            return exe
    return shutil.which("msedge")


def abrir_janela(mostrar_qr=False, revisao=False):
    """Abre a janela do painel (Edge em modo aplicativo). mostrar_qr: já com o QR do celular;
    revisao: já com a revisão da skill gravada."""
    global _janela
    if not _servidor:
        return False
    url = endereco() + ("&qr=1" if mostrar_qr else "") + ("&revisao=1" if revisao else "")
    if _janela and _janela.poll() is None:
        if not (mostrar_qr or revisao):
            return True
        _janela.terminate()                      # reabre já com o QR / a revisão na tela
    exe = _edge()
    if not exe:
        import webbrowser
        webbrowser.open(url)
        return True
    perfil = caminhos.dado("painel_janela")          # perfil próprio: lembra tamanho/posição da janela
    largura, altura = TAMANHO_JANELA
    _janela = subprocess.Popen([exe, f"--app={url}", f"--user-data-dir={perfil}",
                                f"--window-size={largura},{altura}", "--no-first-run",
                                "--no-default-browser-check", "--disable-features=Translate"])
    evento("Painel aberto", "info")
    return True


def _dados_mapa_rede():
    from ghost.servicos import rede
    return rede.dados_mapa()


# Telas de visualização: nome -> (título, função que monta os dados). O desenho fica em painel_web/hud_<nome>.html.
HUDS = {"rede": ("Link neural da rede", _dados_mapa_rede)}
_huds_abertos = {}


def abrir_hud(nome):
    """Abre uma tela de visualização (ex.: 'rede') numa janela própria do Edge. False se não existir."""
    if not _servidor or nome not in HUDS:
        return False
    url = f"http://127.0.0.1:{_servidor.server_address[1]}/hud/{nome}?t={_token}"
    aberta = _huds_abertos.get(nome)
    if aberta and aberta.poll() is None:
        aberta.terminate()                       # reabre na frente, com os dados de agora
    exe = _edge()
    if not exe:
        import webbrowser
        webbrowser.open(url)
        return True
    _huds_abertos[nome] = subprocess.Popen([exe, f"--app={url}", f"--user-data-dir={caminhos.dado('painel_janela')}",
                                            "--window-size=1400,880", "--no-first-run", "--no-default-browser-check",
                                            "--disable-features=Translate"])
    evento(f"HUD aberto: {HUDS[nome][0]}", "info")
    return True


def fechar_janela():
    global _janela
    if _janela and _janela.poll() is None:
        _janela.terminate()
    _janela = None


def iniciar(abrir=None, falar=None):
    """Liga o servidor local e a coleta. abrir=None segue a preferência 'painel_ao_iniciar' (padrão: não; abre por voz).
    falar: para o painel poder falar (ex.: testar uma skill gravada pelo botão)."""
    global _servidor, _falar
    if falar:
        _falar = falar
    if _servidor:
        return
    try:
        _servidor = ThreadingHTTPServer(("127.0.0.1", PORTA), _Rotas)
    except OSError:                               # porta ocupada (outro programa): usa qualquer livre
        _servidor = ThreadingHTTPServer(("127.0.0.1", 0), _Rotas)
    _servidor.daemon_threads = True
    threading.Thread(target=_servidor.serve_forever, daemon=True, name="painel-servidor").start()
    threading.Thread(target=_coletar, daemon=True, name="painel-coleta").start()
    print(f"\n[PAINEL]: pronto em {endereco()}")
    if abrir if abrir is not None else preferencias.carregar().get("painel_ao_iniciar", False):
        abrir_janela()
