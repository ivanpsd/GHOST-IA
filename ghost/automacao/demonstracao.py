"""
GHOST - Skills aprendidas por DEMONSTRAÇÃO: o senhor faz a tarefa, o Ghost assiste e depois repete.

    "Ghost, aprenda uma skill pela tela"  -> começa a gravar (faixa do topo: GRAVANDO)
    ... o senhor faz a tarefa normalmente (cliques, digitação, teclas) ...
    "Ghost, parar de gravar" (ou F10)     -> o painel abre a REVISÃO com os passos e miniaturas
    "teste a skill" / "salve a skill como relatório Débora" / "remova o passo 3" /
    "o passo 4 muda" (vira pergunta na hora de rodar) / "descarte a skill"

Como ele acha o lugar certo na hora de repetir (nesta ordem):
1. pelo TEXTO perto do clique ("Incluir", "Cliente"), lido com o OCR do Windows, esperando a tela aparecer;
2. pelo RECORTE de imagem em volta do clique;
3. pela posição relativa na janela, só se a janela estiver do mesmo tamanho.
Se não achar, PARA e avisa (nunca clica no escuro). F10 interrompe a execução a qualquer momento.

Segurança: o que é digitado logo depois de clicar perto de "Senha" NÃO é gravado; na execução o Ghost
pede para o senhor digitar na hora. As fotos ficam só em dados/skills/ (fora do Git).
"""
import os
import re
import shutil
import threading
import time
import uuid

from ghost.automacao import periodo
from ghost.nucleo import caminhos

PASTA = caminhos.dado("skills")
PASTA_RASCUNHO = os.path.join(PASTA, "rascunho")
LIMITE_GRAVACAO_S = 600
DUPLO_CLIQUE_S = 0.45
ESPERA_MAX_S = 25                 # tempo máximo procurando o botão/texto de um passo
ESPERA_MIN_S = 6
RECORTE = (160, 70)               # largura x altura da imagem guardada em volta do clique
PALAVRAS_SENHA = ("senha", "password", "pin", "token", "codigo de acesso")
IGNORAR_JANELAS = ("painel do ghost",)          # cliques na tela do próprio Ghost não entram na skill
TECLAS_FALAR = ("f9",)                           # F9 é o "falar" do Ghost: não vira passo

_trava = threading.Lock()
_gravacao = None                 # Gravacao em andamento
_rascunho = None                 # {"passos": [...], "nome", "gatilho"} esperando revisão
_abortar = threading.Event()
_executando = threading.Lock()


# =============================================================
# 1. GRAVAÇÃO (eventos brutos)
# =============================================================
class Gravacao:
    def __init__(self, ao_parar=None):
        self.eventos = []
        self.ao_parar = ao_parar
        self._t0 = time.time()
        self._texto = []                     # digitação em andamento
        self._mods = set()
        self._parado = threading.Event()
        self._ouvintes = []

    # ---------- mouse
    def _clique(self, x, y, botao, pressionado):
        if not pressionado or self._parado.is_set():
            return
        try:
            from ghost.visao import olho
            j = olho.janela_no_ponto(x, y)
            if j["classe"] in ("Shell_TrayWnd", "Shell_SecondaryTrayWnd") or \
                    any(i in olho.normalizar(j["titulo"]) for i in IGNORAR_JANELAS):
                return
            ant = self.eventos[-1] if self.eventos else None
            if ant and ant["tipo"] == "clique" and time.time() - ant["t"] < DUPLO_CLIQUE_S \
                    and abs(ant["x"] - x) < 6 and abs(ant["y"] - y) < 6:
                ant["duplo"] = True
                return
            self._fechar_texto()
            try:
                foto = olho.capturar(j["hwnd"])           # a tela como estava NO clique (~60 ms)
            except Exception:
                foto = None
            self.eventos.append({"tipo": "clique", "t": time.time(), "x": int(x), "y": int(y),
                                 "botao": getattr(botao, "name", str(botao)), "duplo": False, "janela": j, "foto": foto})
        except Exception as e:
            print(f"\n[GRAVAÇÃO]: clique não registrado ({e!r}).")

    def _rolar(self, x, y, dx, dy):
        if self._parado.is_set():
            return
        ant = self.eventos[-1] if self.eventos else None
        if ant and ant["tipo"] == "rolar" and time.time() - ant["t"] < 1.5:
            ant["dy"] += dy
            ant["t"] = time.time()
            return
        self._fechar_texto()
        self.eventos.append({"tipo": "rolar", "t": time.time(), "x": int(x), "y": int(y), "dy": dy})

    # ---------- teclado
    def _nome(self, k):
        nome = getattr(k, "name", None)
        return nome.lower() if nome else None

    def _tecla_baixo(self, k):
        if self._parado.is_set():
            return
        nome = self._nome(k)
        if nome == "f10":
            self.parar()
            return
        if nome in TECLAS_FALAR:
            return
        if nome in ("ctrl_l", "ctrl_r", "ctrl", "alt_l", "alt_r", "alt", "alt_gr", "shift", "shift_l", "shift_r",
                    "cmd", "cmd_l", "cmd_r"):
            self._mods.add(nome.split("_")[0])
            return
        char = getattr(k, "char", None)
        if char and char.isprintable() and not ({"ctrl", "alt", "cmd"} & self._mods):
            self._texto.append(char)
            return
        if nome == "space" and not ({"ctrl", "alt", "cmd"} & self._mods):
            self._texto.append(" ")
            return
        if nome == "backspace" and self._texto:
            self._texto.pop()
            return
        self._fechar_texto()
        mods = [m for m in ("ctrl", "alt", "shift", "cmd") if m in self._mods]
        tecla = nome or (char or "").lower() or str(getattr(k, "vk", ""))
        if char and not nome and ({"ctrl", "alt", "cmd"} & self._mods):
            vk = getattr(k, "vk", None)                       # ctrl+c chega como caractere de controle
            tecla = chr(vk).lower() if vk and 48 <= vk <= 90 else tecla
        if mods == ["shift"] and nome in ("tab",):
            mods = ["shift"]
        self.eventos.append({"tipo": "tecla", "t": time.time(), "combo": "+".join(mods + [tecla.replace("cmd", "win")])})

    def _tecla_cima(self, k):
        nome = self._nome(k)
        if nome:
            self._mods.discard(nome.split("_")[0])

    def _fechar_texto(self):
        if self._texto:
            self.eventos.append({"tipo": "digitar", "t": time.time(), "texto": "".join(self._texto)})
            self._texto = []

    # ---------- controle
    def iniciar(self):
        from pynput import keyboard as kb
        from pynput import mouse as ms
        self._ouvintes = [ms.Listener(on_click=self._clique, on_scroll=self._rolar),
                          kb.Listener(on_press=self._tecla_baixo, on_release=self._tecla_cima)]
        for o in self._ouvintes:
            o.start()
        threading.Timer(LIMITE_GRAVACAO_S, self.parar).start()

    def parar(self):
        if self._parado.is_set():
            return
        self._parado.set()
        self._fechar_texto()
        for o in self._ouvintes:
            try:
                o.stop()
            except Exception:
                pass
        if self.ao_parar:
            threading.Thread(target=self.ao_parar, args=(self,), daemon=True, name="gravacao-fim").start()


# =============================================================
# 2. EVENTOS -> PASSOS (com OCR em volta de cada clique)
# =============================================================
def _perto_de_senha(palavras, x, y, raio=220):
    from ghost.visao import olho
    for p in palavras:
        if any(s in olho.normalizar(p["texto"]) for s in PALAVRAS_SENHA):
            px, py = p["x"] + p["w"] / 2, p["y"] + p["h"] / 2
            if abs(px - x) < raio and abs(py - y) < 60:
                return True
    return False


def montar_passos(eventos, ler=None, pasta=None):
    """Transforma os eventos gravados em passos. `ler(foto)` devolve as palavras do OCR (injetável nos testes)."""
    from ghost.visao import olho
    ler = ler or olho.ler
    passos = []
    janela_ant = None
    senha_pendente = False
    for ev in eventos:
        if ev["tipo"] == "clique":
            j = ev["janela"]
            foto = ev.get("foto")
            origem = (foto.info.get("origem") if foto is not None else None) or j["rect"][:2]
            x, y = ev["x"] - origem[0], ev["y"] - origem[1]
            palavras = []
            if foto is not None:
                try:
                    palavras = ler(foto)
                except Exception as e:
                    print(f"\n[GRAVAÇÃO]: OCR falhou ({e!r}).")
            ancora = olho.ancora_do_clique(palavras, x, y)
            senha_pendente = _perto_de_senha(palavras, x, y)
            p = {"acao": "clicar", "janela": {"exe": j["exe"], "base": olho.nome_base(j["titulo"]), "titulo": j["titulo"]},
                 "ancora": ancora, "botao": ev["botao"], "duplo": ev.get("duplo", False),
                 "rel": [round(x / max(1, foto.width if foto is not None else j["rect"][2]), 4),
                         round(y / max(1, foto.height if foto is not None else j["rect"][3]), 4)],
                 "tamanho": list(foto.size) if foto is not None else list(j["rect"][2:]),
                 "recorte": None, "nova_janela": janela_ant is None or janela_ant != (j["exe"], olho.nome_base(j["titulo"])),
                 "abs": [ev["x"], ev["y"]],
                 # lista aberta de um campo (janelinha sem título do Chrome): na execução procura na tela toda
                 "popup": not j["titulo"].strip()}
            if foto is not None and pasta:
                w, h = RECORTE
                caixa = (max(0, x - w // 2), max(0, y - h // 2), min(foto.width, x + w // 2), min(foto.height, y + h // 2))
                nome = f"p{len(passos) + 1}_{uuid.uuid4().hex[:6]}.png"
                os.makedirs(pasta, exist_ok=True)
                foto.crop(caixa).save(os.path.join(pasta, nome))
                p["recorte"] = nome
                p["recorte_centro"] = [x - caixa[0], y - caixa[1]]
            if not p["popup"]:
                janela_ant = (j["exe"], olho.nome_base(j["titulo"]))
            passos.append(p)
        elif ev["tipo"] == "digitar":
            if senha_pendente:
                passos.append({"acao": "digitar", "texto": "", "segredo": True, "variavel": None})
                senha_pendente = False
            elif periodo.parece_data(ev["texto"]):
                # data digitada ("26/10/2026"): vira campo de data, preenchido pelo período do pedido
                ant = next((q for q in reversed(passos) if q["acao"] == "clicar"), None)
                rotulo = ant["ancora"]["texto"] if ant and ant.get("ancora") else "a data"
                passos.append({"acao": "digitar", "texto": "", "segredo": False, "variavel": rotulo, "tipo": "data",
                               "formato": periodo.formato_de(ev["texto"]), "exemplo": ev["texto"]})
            else:
                passos.append({"acao": "digitar", "texto": ev["texto"], "segredo": False, "variavel": None})
        elif ev["tipo"] == "tecla":
            passos.append({"acao": "tecla", "combo": ev["combo"]})
        elif ev["tipo"] == "rolar":
            passos.append({"acao": "rolar", "dy": ev["dy"]})
    # tempo entre um passo e outro (ajuda a decidir quanto esperar a tela na execução)
    for i, ev in enumerate(eventos[:len(passos)]):
        passos[i]["pausa"] = round(min(30.0, ev["t"] - eventos[i - 1]["t"]), 1) if i else 0.0
    _papeis_das_datas(passos)
    return passos


def _papeis_das_datas(passos):
    """Qual campo de data é o início e qual é o fim ("Da Data" / "Até a Data")."""
    datas = [p for p in passos if p.get("tipo") == "data" and p.get("variavel")]
    for i, p in enumerate(datas):
        p["papel"] = periodo.papel(p["variavel"], i)
    if len(datas) == 2 and datas[0]["papel"] == datas[1]["papel"]:
        datas[0]["papel"], datas[1]["papel"] = "inicio", "fim"


def avisos(passos):
    """Coisas que não vão repetir bem (mostradas na revisão)."""
    saida = []
    dias = [i for i, p in enumerate(passos, 1) if p["acao"] == "clicar" and p.get("ancora")
            and re.fullmatch(r"\d{1,2}", p["ancora"]["texto"].strip())]
    if dias:
        saida.append(f"Os passos {', '.join(map(str, dias))} escolhem um dia no calendário: na próxima vez o calendário "
                     "estará em outro mês e não vai bater. Grave de novo DIGITANDO a data no campo (ex.: 01/10/2026): "
                     "aí o Ghost troca a data sozinho conforme o pedido.")
    sem = [i for i, p in enumerate(passos, 1) if p["acao"] == "clicar" and not p.get("ancora") and not p.get("recorte")]
    if sem:
        saida.append(f"Os passos {', '.join(map(str, sem))} não têm texto nem imagem para conferir.")
    return saida


def descrever(p):
    a = p["acao"]
    if a == "clicar":
        alvo = f"“{p['ancora']['texto']}”" if p.get("ancora") else "um ponto sem texto"
        tipo = "Clique duplo em" if p.get("duplo") else ("Clique direito em" if p.get("botao") == "right" else "Clicar em")
        return f"{tipo} {alvo} ({p['janela']['base'] or p['janela']['exe']})"
    if a == "digitar":
        if p.get("segredo"):
            return "Digitar a senha (o senhor digita na hora; não fica gravada)"
        if p.get("tipo") == "data" and p.get("variavel"):
            qual = "inicial" if p.get("papel") == "inicio" else "final"
            return f"Digitar a data {qual} em “{p['variavel']}” (vem do pedido: “mês passado”, “de 1 a 15 de outubro”…)"
        if p.get("variavel"):
            return f"Digitar “{p['variavel']}” (perguntado na hora)"
        return f"Digitar “{p['texto'][:60]}”"
    if a == "tecla":
        return f"Apertar {p['combo'].replace('+', ' + ')}"
    if a == "rolar":
        return "Rolar para " + ("cima" if p["dy"] > 0 else "baixo")
    return a


# =============================================================
# 3. RASCUNHO (revisão antes de salvar)
# =============================================================
def gravando():
    return _gravacao is not None


def iniciar_gravacao(falar, ao_terminar=None):
    """Começa a gravar. ao_terminar(rascunho) é chamado quando os passos estiverem prontos."""
    global _gravacao
    with _trava:
        if _gravacao:
            falar("Já estou gravando, senhor. Diga parar de gravar quando terminar.")
            return
        shutil.rmtree(PASTA_RASCUNHO, ignore_errors=True)

        def fim(g):
            global _gravacao, _rascunho
            try:
                passos = montar_passos(g.eventos, pasta=PASTA_RASCUNHO)
            except Exception as e:
                passos = []
                print(f"\n[GRAVAÇÃO]: falha ao montar os passos ({e!r}).")
            with _trava:
                _gravacao = None
                _rascunho = {"passos": passos, "nome": "", "gatilho": "", "criado": time.strftime("%Y-%m-%d %H:%M"),
                             "avisos": avisos(passos)}
            if ao_terminar:
                ao_terminar(_rascunho)

        _gravacao = Gravacao(ao_parar=fim)
        _gravacao.iniciar()
    falar("Gravando, senhor. Faça a tarefa normalmente; quando terminar, diga parar de gravar ou aperte F10.")


def parar_gravacao():
    g = _gravacao
    if g:
        g.parar()
        return True
    return False


def rascunho():
    return _rascunho


def remover_passo(n):
    with _trava:
        if not _rascunho or not 1 <= n <= len(_rascunho["passos"]):
            return False
        _rascunho["passos"].pop(n - 1)
        return True


def marcar_variavel(n, rotulo=None, ligar=True):
    """O texto digitado no passo n muda a cada vez: vira pergunta na hora de rodar. ligar=False: volta a ser fixo."""
    with _trava:
        if not _rascunho or not 1 <= n <= len(_rascunho["passos"]):
            return False
        p = _rascunho["passos"][n - 1]
        if p["acao"] != "digitar" or p.get("segredo"):
            return False
        if not ligar:
            if not p.get("variavel"):
                return False
            p["texto"] = p.pop("exemplo", "") or p.get("texto", "")
            p["variavel"] = None
            p.pop("tipo", None)
            p.pop("papel", None)
            _papeis_das_datas(_rascunho["passos"])
            return True
        if not rotulo:                                   # usa o rótulo do campo clicado antes ("Cliente")
            ant = next((q for q in reversed(_rascunho["passos"][:n - 1]) if q["acao"] == "clicar"), None)
            rotulo = (ant or {}).get("ancora", {}) and ant["ancora"]["texto"] or f"o valor do passo {n}"
        p["variavel"] = rotulo
        p["exemplo"] = p.get("texto") or p.get("exemplo", "")
        p["texto"] = ""
        if periodo.parece_data(p["exemplo"]):
            p["tipo"], p["formato"] = "data", periodo.formato_de(p["exemplo"])
            _papeis_das_datas(_rascunho["passos"])
        return True


def definir_nome(nome, gatilho=None):
    with _trava:
        if not _rascunho:
            return False
        _rascunho["nome"] = nome.strip()
        _rascunho["gatilho"] = (gatilho or nome).strip()
        return True


def descartar():
    global _rascunho
    with _trava:
        _rascunho = None
    shutil.rmtree(PASTA_RASCUNHO, ignore_errors=True)


def salvar():
    """Salva o rascunho como skill. Devolve a skill ou levanta ValueError com o motivo."""
    global _rascunho
    from ghost.ia import skills
    with _trava:
        r = _rascunho
        if not r or not r["passos"]:
            raise ValueError("não há skill gravada para salvar")
        if not r["nome"]:
            raise ValueError("falta o nome. Diga: salve a skill como, e o nome")
        sid = "d_" + uuid.uuid4().hex[:8]
        pasta = os.path.join(PASTA, sid)
        if os.path.isdir(PASTA_RASCUNHO):
            shutil.copytree(PASTA_RASCUNHO, pasta, dirs_exist_ok=True)
        skill = {"id": sid, "tipo": "demonstracao", "nome": r["nome"], "gatilhos": [r["gatilho"]],
                 "resumo": f"{len(r['passos'])} passos gravados na tela", "passos": r["passos"],
                 "criada": r["criado"], "pasta": sid}
        skills.salvar(skill)
        _rascunho = None
    shutil.rmtree(PASTA_RASCUNHO, ignore_errors=True)
    return skill


# =============================================================
# 4. EXECUÇÃO
# =============================================================
class Parou(Exception):
    """A execução parou (não achou algo, F10, ou o senhor cancelou). A mensagem é falada."""


def abortar():
    _abortar.set()


def em_execucao():
    return _executando.locked()


def _esperar(segundos):
    if _abortar.wait(segundos):
        raise Parou("Parei: o senhor apertou F10.")


def _localizar(p, janela, pasta, leitor=None):
    """(x, y) na TELA para o clique do passo p, ou None. Tenta texto, recorte e posição relativa."""
    from PIL import Image

    from ghost.visao import olho
    if p.get("popup"):                     # lista aberta de um campo: janelinha própria, procura na tela toda
        foto = olho.capturar_tela()
        ox, oy = foto.info["origem"]
        esperado = (p["abs"][0] - ox, p["abs"][1] - oy)
    else:
        foto = olho.capturar(janela["hwnd"])
        ox, oy = foto.info.get("origem", janela["rect"][:2])
        esperado = (p["rel"][0] * foto.width, p["rel"][1] * foto.height)
    a = p.get("ancora")
    if a:
        palavras = (leitor or olho.ler)(foto)
        achados = olho.achar_texto(palavras, a["texto"], perto=esperado)
        if achados:
            c = achados[0]
            return ox + c["x"] + c["w"] / 2 + a["dx"], oy + c["y"] + c["h"] / 2 + a["dy"]
    if p.get("recorte") and pasta:
        caminho = os.path.join(pasta, p["recorte"])
        if os.path.exists(caminho):
            with Image.open(caminho) as rec:
                achado = olho.achar_imagem(foto, rec)
                if achado:
                    cx, cy = p.get("recorte_centro", [rec.width // 2, rec.height // 2])
                    return ox + achado[0] - rec.width // 2 + cx, oy + achado[1] - rec.height // 2 + cy
    if not a and not p.get("popup") and list(foto.size) == p.get("tamanho"):   # sem texto e janela igual: posição relativa
        return ox + p["rel"][0] * foto.width, oy + p["rel"][1] * foto.height
    return None


def _janela_do_passo(p, falar):
    from ghost.visao import olho
    j = p["janela"]
    limite = time.time() + max(ESPERA_MIN_S, min(ESPERA_MAX_S, p.get("pausa", 0) * 3))
    abriu = False
    while True:
        achada = olho.achar_janela(j["exe"], j["base"])
        if achada:
            return achada
        if not abriu:                                        # não está aberta: tenta abrir pelo nome
            abriu = True
            try:
                from ghost.automacao import apps
                app, conf = apps.encontrar(j["base"])
                if app and conf >= apps.CONFIANCA_MINIMA:
                    falar(f"Abrindo {app['nome']}, senhor.")
                    apps.abrir(app)
                    limite = time.time() + 40
            except Exception as e:
                print(f"\n[SKILL]: não consegui abrir {j['base']} ({e!r}).")
        if time.time() > limite:
            raise Parou(f"Parei: não encontrei a janela {j['base'] or j['exe']}. Abra e peça de novo, senhor.")
        _esperar(1)


def _periodo_da_ia(texto, hoje):
    """Último recurso para entender o período ("primeira quinzena do mês passado"): pergunta à IA."""
    try:
        import json

        from ghost.ia import skills
        r = skills._groq().chat.completions.create(
            model="openai/gpt-oss-20b", temperature=0, max_tokens=200, response_format={"type": "json_object"},
            messages=[{"role": "user", "content": (
                f"Hoje é {hoje:%d/%m/%Y}. Converta o período desta frase em datas. Responda só JSON "
                '{"inicio": "AAAA-MM-DD", "fim": "AAAA-MM-DD"} ou {"inicio": null} se não houver período. '
                f"Frase: {texto}")}])
        j = json.loads(r.choices[0].message.content)
        if not j.get("inicio"):
            return None
        from datetime import date
        ini, fim = date.fromisoformat(j["inicio"]), date.fromisoformat(j.get("fim") or j["inicio"])
        return (ini, fim) if ini <= fim else (fim, ini)
    except Exception as e:
        print(f"\n[SKILL]: IA não entendeu o período ({e!r}).")
        return None


def valores_das_variaveis(passos, frase, perguntar, hoje=None):
    """{índice do passo: texto a digitar}. Datas vêm do período dito no pedido (ou perguntado uma vez só);
    as outras variáveis são perguntadas uma a uma."""
    from datetime import date
    hoje = hoje or date.today()
    valores = {}
    datas = [(i, p) for i, p in enumerate(passos) if p["acao"] == "digitar" and p.get("tipo") == "data" and p.get("variavel")]
    if datas:
        per = periodo.interpretar(frase or "", hoje)
        if per is None:
            r = perguntar("Qual o período, senhor? Por exemplo: mês passado, ou de 1 a 15 de outubro.")
            if r is None:
                raise Parou("Cancelado, senhor.")
            per = periodo.interpretar(r, hoje) or _periodo_da_ia(r, hoje)
            if per is None:
                raise Parou("Não entendi o período, senhor. Peça de novo dizendo as datas, por exemplo: de 01/10 a 15/10.")
        for i, p in datas:
            d = per[1] if p.get("papel") == "fim" else per[0]
            valores[i] = d.strftime(p.get("formato") or "%d/%m/%Y")
    for i, p in enumerate(passos):
        if p["acao"] == "digitar" and p.get("variavel") and i not in valores:
            r = perguntar(f"Qual {p['variavel']}, senhor?")
            if r is None:
                raise Parou("Cancelado, senhor.")
            valores[i] = r.strip()
    return valores


def executar(skill, falar, perguntar, teste=False, frase=""):
    """Repete os passos gravados. perguntar(pergunta) -> resposta (texto) ou None (cancelado).
    frase: o pedido original ("relatório de faturamento do mês passado"), de onde saem as datas."""
    import pyautogui
    from pynput import keyboard as kb

    from ghost.automacao import automacoes
    from ghost.visao import olho
    if not _executando.acquire(blocking=False):
        falar("Já estou rodando uma skill, senhor.")
        return False
    _abortar.clear()
    ouvinte = kb.Listener(on_press=lambda k: _abortar.set() if getattr(k, "name", "") == "f10" else None)
    ouvinte.start()
    pasta = os.path.join(PASTA, skill.get("pasta", "")) if skill.get("pasta") else PASTA_RASCUNHO
    passos = skill["passos"]
    try:
        # as respostas variáveis são resolvidas ANTES de começar (para não parar no meio da tela)
        valores = valores_das_variaveis(passos, frase, perguntar)
        datas = [valores[i] for i, p in enumerate(passos) if i in valores and p.get("tipo") == "data"]
        if datas:
            falar(f"Período de {datas[0]}" + (f" até {datas[-1]}" if len(datas) > 1 else "") + ", senhor.")
        janela = None
        for i, p in enumerate(passos, 1):
            if _abortar.is_set():
                raise Parou("Parei: o senhor apertou F10.")
            if teste:
                print(f"\n[SKILL TESTE]: {i}. {descrever(p)}")
            if p["acao"] == "clicar" and p.get("popup") and janela is not None:
                limite = time.time() + ESPERA_MIN_S
                ponto = None
                while ponto is None:
                    ponto = _localizar(p, janela, pasta)
                    if ponto is None:
                        if time.time() > limite:
                            alvo = p["ancora"]["texto"] if p.get("ancora") else "a opção da lista"
                            raise Parou(f"Parei no passo {i}: a lista não mostrou “{alvo}”. Nada mais foi feito.")
                        _esperar(0.6)
                pyautogui.click(int(ponto[0]), int(ponto[1]))
            elif p["acao"] == "clicar":
                if p.get("nova_janela") or janela is None or not olho.achar_janela(janela["exe"], olho.nome_base(janela["titulo"])):
                    janela = _janela_do_passo(p, falar)
                    olho.focar(janela["hwnd"])
                    _esperar(0.4)
                limite = time.time() + max(ESPERA_MIN_S, min(ESPERA_MAX_S, p.get("pausa", 0) * 3))
                ponto = None
                while ponto is None:
                    janela = olho.achar_janela(janela["exe"], olho.nome_base(janela["titulo"])) or janela
                    ponto = _localizar(p, janela, pasta)
                    if ponto is None:
                        if time.time() > limite:
                            alvo = p["ancora"]["texto"] if p.get("ancora") else "o ponto do clique"
                            raise Parou(f"Parei no passo {i}: não achei “{alvo}” na tela. Nada mais foi feito.")
                        _esperar(0.8)
                olho.focar(janela["hwnd"])
                botao = "right" if p.get("botao") == "right" else "left"
                pyautogui.click(int(ponto[0]), int(ponto[1]), clicks=2 if p.get("duplo") else 1, interval=0.08, button=botao)
            elif p["acao"] == "digitar":
                if p.get("segredo"):
                    r = perguntar("Senhor, digite a senha agora e diga continuar.")
                    if r is None:
                        raise Parou("Cancelado, senhor.")
                elif (i - 1) in valores:                     # variável: apaga o que havia no campo e digita
                    pyautogui.hotkey("ctrl", "a")
                    _esperar(0.1)
                    if p.get("tipo") == "data":
                        pyautogui.write(valores[i - 1], interval=0.03)   # campo com máscara: tecla por tecla
                    else:
                        automacoes._colar(valores[i - 1])
                else:
                    automacoes._colar(p.get("texto", ""))
            elif p["acao"] == "tecla":
                pyautogui.hotkey(*[t.replace("win", "winleft") for t in p["combo"].split("+")])
            elif p["acao"] == "rolar":
                pyautogui.scroll(int(p["dy"]) * 120)
            _esperar(0.35)
        falar(("Teste concluído, senhor. Se ficou certo, diga salvar a skill." if teste
               else f"Skill {skill['nome']} concluída, senhor."))
        return True
    except Parou as e:
        falar(str(e))
        return False
    except Exception as e:
        print(f"\n[SKILL]: erro na execução ({e!r}).")
        falar(f"Senhor, a skill parou por um erro: {e}.")
        return False
    finally:
        ouvinte.stop()
        _executando.release()
