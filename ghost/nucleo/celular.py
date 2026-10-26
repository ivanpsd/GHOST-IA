"""
GHOST - App do celular com segurança: pareamento, PIN, aparelhos registrados e Tailscale.

Como o celular chega ao Ghost (escolhido sozinho, nesta ordem):
1. Tailscale (recomendado): rede particular criptografada entre o PC e o celular. Funciona no 5G,
   em casa e no escritório; o Ghost não abre porta nenhuma na rede da empresa (o servidor do celular
   escuta só em 127.0.0.1 e o Tailscale publica em https://<nome-do-pc>.<sua-rede>.ts.net).
   Com https o navegador libera o microfone: dá para FALAR com o Ghost pelo celular.
2. Rede local (sem Tailscale): só no mesmo Wi-Fi, sem criptografia, e só se a rede do Windows for
   Privada ou de Domínio. Se o PC passar para uma rede Pública, o acesso desliga sozinho.

Camadas de proteção (valem nos dois caminhos):
- Pareamento: o QR / código de 6 letras vale 5 minutos, uma vez só, 5 tentativas.
- PIN de 6 dígitos (criado no 1º pareamento; guardado só como hash PBKDF2).
- Cada celular vira um "aparelho" com chave própria (guardada só como hash) e pode ser removido.
- Ao abrir o app: PIN. A sessão vale 12 h. 5 PINs errados: aparelho bloqueado 15 min; 15 seguidos: removido.
- Ações sensíveis pedidas pelo celular (WhatsApp, digitar, teclas, fechar programas, desligar, skills)
  pedem confirmação no próprio app.
Arquivo: dados/celular.json (fora do Git).
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from ghost.nucleo import arquivo, caminhos, preferencias

ARQUIVO = caminhos.dado("celular.json")
PORTA = 8766
PAREAMENTO_S = 300            # validade do QR / código de pareamento
TENTATIVAS_CODIGO = 5
SESSAO_S = 12 * 3600          # depois disso o app pede o PIN de novo
ERROS_BLOQUEIO = 5            # PINs errados seguidos -> bloqueio temporário
BLOQUEIO_S = 15 * 60
ERROS_REMOCAO = 15            # PINs errados seguidos -> o aparelho é removido
MAX_AUDIO = 8_000_000         # ~2 min de áudio do celular
ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # sem 0/O e 1/I/L (fácil de digitar)
REDES_PERMITIDAS = {"Private", "DomainAuthenticated"}
CREATE_NO_WINDOW = 0x08000000

_trava = threading.RLock()
_pareamento = None            # {"codigo", "expira", "tentativas"}
_sessoes = {}                 # token -> {"aparelho": id, "expira": t}
_erros = {}                   # id do aparelho -> {"n": erros seguidos, "ate": bloqueado até}
_servidor = None
_modo = None                  # "tailscale" | "rede local" | None
_base = None                  # https://pc.rede.ts.net  ou  http://192.168.0.25:8766
_entregar = None              # põe o pedido na fila do Ghost
_avisar = None                # fala no PC (ex.: "aparelho pareado")


class ErroCelular(Exception):
    """Mensagem já pronta para mostrar no celular."""


# =============================================================
# 1. ARMAZENAMENTO (aparelhos e PIN)
# =============================================================
def _carregar():
    try:
        dados = arquivo.ler_json(ARQUIVO, {}) or {}
    except arquivo.ArquivoCorrompido:
        dados = {}
    if not isinstance(dados, dict) or "token" in dados:       # formato antigo (link fixo, sem PIN): descartado
        dados = {}
    dados.setdefault("aparelhos", [])
    return dados


def _salvar(dados):
    arquivo.salvar_json(ARQUIVO, dados)


def _hash(texto):
    return hashlib.sha256(texto.encode()).hexdigest()


def _hash_pin(pin, sal):
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(sal), 200_000).hex()


def tem_pin():
    with _trava:
        return bool(_carregar().get("pin"))


def aparelhos():
    """Aparelhos pareados (sem as chaves)."""
    with _trava:
        return [{k: a.get(k) for k in ("id", "nome", "criado", "ultimo_uso")} for a in _carregar()["aparelhos"]]


def remover(aparelho_id):
    with _trava:
        dados = _carregar()
        antes = len(dados["aparelhos"])
        dados["aparelhos"] = [a for a in dados["aparelhos"] if a["id"] != aparelho_id]
        _salvar(dados)
        for t in [t for t, s in _sessoes.items() if s["aparelho"] == aparelho_id]:
            _sessoes.pop(t, None)
    _evento(f"Aparelho removido ({aparelho_id})", "alerta")
    return antes != len(dados["aparelhos"])


def remover_todos():
    with _trava:
        dados = _carregar()
        dados["aparelhos"] = []
        _salvar(dados)
        _sessoes.clear()
    _evento("Todos os celulares foram removidos", "alerta")


def trocar_pin():
    """Esqueceu o PIN: apaga o PIN e todos os aparelhos (cada celular pareia de novo e cria um PIN novo)."""
    with _trava:
        _salvar({"aparelhos": []})
        _sessoes.clear()
        _erros.clear()
    _evento("PIN do celular apagado; todos os aparelhos precisam parear de novo", "alerta")


# =============================================================
# 2. PAREAMENTO, PIN E SESSÃO
# =============================================================
def novo_codigo():
    """Código de pareamento: 6 letras/números, 5 minutos, uma vez só."""
    global _pareamento
    with _trava:
        _pareamento = {"codigo": "".join(secrets.choice(ALFABETO) for _ in range(6)),
                       "expira": time.time() + PAREAMENTO_S, "tentativas": 0}
        return dict(_pareamento)


def codigo_atual():
    with _trava:
        if _pareamento and time.time() < _pareamento["expira"]:
            return dict(_pareamento)
        return None


def _limpo(codigo):
    return "".join(c for c in str(codigo or "").upper() if c.isalnum())


def _pin_valido(pin):
    return isinstance(pin, str) and len(pin) == 6 and pin.isdigit()


def parear(codigo, nome, pin, pin_confirmacao=None):
    """Registra um celular. Devolve {"aparelho_token", "sessao", "nome"}. Levanta ErroCelular."""
    global _pareamento
    with _trava:
        p = _pareamento
        if not p or time.time() > p["expira"]:
            raise ErroCelular("Código vencido. Diga \"Ghost, conectar celular\" para gerar outro.")
        p["tentativas"] += 1
        if p["tentativas"] > TENTATIVAS_CODIGO:
            _pareamento = None
            raise ErroCelular("Tentativas demais. Gere um código novo no PC.")
        if not hmac.compare_digest(_limpo(codigo), p["codigo"]):
            raise ErroCelular("Código errado. Confira as 6 letras mostradas no PC.")
        dados = _carregar()
        if not dados.get("pin"):
            if not _pin_valido(pin):
                raise ErroCelular("O PIN precisa ter 6 números.")
            if pin != pin_confirmacao:
                raise ErroCelular("Os dois PINs não são iguais.")
            dados["sal"] = secrets.token_hex(16)
            dados["pin"] = _hash_pin(pin, dados["sal"])
        elif not _pin_valido(pin) or not hmac.compare_digest(_hash_pin(pin, dados["sal"]), dados["pin"]):
            raise ErroCelular("PIN errado.")
        token = secrets.token_urlsafe(32)
        nome = (str(nome or "").strip() or "Celular")[:40]
        aparelho = {"id": secrets.token_hex(4), "nome": nome, "chave": _hash(token),
                    "criado": datetime.now().isoformat(timespec="seconds"), "ultimo_uso": None}
        dados["aparelhos"].append(aparelho)
        _salvar(dados)
        _pareamento = None                        # uma vez só
    _evento(f"Celular pareado: {nome}", "alerta")
    if _avisar:
        _avisar(f"Senhor, o aparelho {nome} foi pareado ao Ghost.")
    return {"aparelho_token": token, "sessao": _abrir_sessao(aparelho["id"]), "nome": nome}


def _abrir_sessao(aparelho_id):
    token = secrets.token_urlsafe(32)
    with _trava:
        agora = time.time()
        for t in [t for t, s in _sessoes.items() if s["expira"] < agora]:
            _sessoes.pop(t, None)
        _sessoes[token] = {"aparelho": aparelho_id, "expira": agora + SESSAO_S}
        dados = _carregar()
        for a in dados["aparelhos"]:
            if a["id"] == aparelho_id:
                a["ultimo_uso"] = datetime.now().isoformat(timespec="seconds")
        _salvar(dados)
    return token


def entrar(aparelho_token, pin):
    """PIN ao abrir o app. Devolve {"sessao", "nome"}."""
    with _trava:
        dados = _carregar()
        chave = _hash(str(aparelho_token or ""))
        aparelho = next((a for a in dados["aparelhos"] if hmac.compare_digest(a["chave"], chave)), None)
        if not aparelho:
            raise ErroCelular("Este celular não está pareado (ou foi removido). Pareie de novo pelo QR code.")
        e = _erros.setdefault(aparelho["id"], {"n": 0, "ate": 0.0})
        if time.time() < e["ate"]:
            raise ErroCelular(f"Bloqueado por PIN errado. Tente de novo em {int((e['ate'] - time.time()) / 60) + 1} min.")
        if not dados.get("pin") or not _pin_valido(pin) or not hmac.compare_digest(_hash_pin(pin, dados["sal"]), dados["pin"]):
            e["n"] += 1
            if e["n"] >= ERROS_REMOCAO:
                _erros.pop(aparelho["id"], None)
                remover(aparelho["id"])
                raise ErroCelular("PIN errado vezes demais: este celular foi removido do Ghost.")
            if e["n"] % ERROS_BLOQUEIO == 0:
                e["ate"] = time.time() + BLOQUEIO_S
                _evento(f"Celular {aparelho['nome']} bloqueado por PIN errado", "alerta")
                raise ErroCelular("PIN errado 5 vezes: bloqueado por 15 minutos.")
            raise ErroCelular(f"PIN errado. Restam {ERROS_BLOQUEIO - e['n'] % ERROS_BLOQUEIO} tentativas.")
        _erros.pop(aparelho["id"], None)
    _evento(f"Celular conectado: {aparelho['nome']}", "info")
    return {"sessao": _abrir_sessao(aparelho["id"]), "nome": aparelho["nome"]}


def sessao(token):
    """Aparelho da sessão (dict) ou None."""
    with _trava:
        s = _sessoes.get(str(token or ""))
        if not s or s["expira"] < time.time():
            _sessoes.pop(str(token or ""), None)
            return None
        return next((a for a in _carregar()["aparelhos"] if a["id"] == s["aparelho"]), None)


def sair(token):
    with _trava:
        _sessoes.pop(str(token or ""), None)


# =============================================================
# 3. CAMINHO DE REDE: TAILSCALE OU REDE LOCAL
# =============================================================
def _rodar(args, timeout=15):
    """(código, saída). Se o programa ficar esperando (ex.: "tailscale serve" aguardando você ativar o recurso
    no site), encerra depois de `timeout` e devolve (None, o que ele escreveu até ali)."""
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
    try:
        saida, _ = p.communicate(timeout=timeout)
        return p.returncode, (saida or b"").decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        p.kill()
        saida, _ = p.communicate()
        return None, (saida or b"").decode("utf-8", "replace")


def tailscale_exe():
    exe = shutil.which("tailscale")
    if exe:
        return exe
    for base in (os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", "")):
        p = os.path.join(base, "Tailscale", "tailscale.exe")
        if base and os.path.exists(p):
            return p
    return None


def tailscale_nome():
    """Nome https do PC na rede Tailscale (ex.: ti-ivan.tail1234.ts.net) ou None se não estiver ligado."""
    exe = tailscale_exe()
    if not exe:
        return None
    codigo, saida = _rodar([exe, "status", "--json"])
    if codigo != 0:
        return None
    try:
        st = json.loads(saida[saida.index("{"):])
    except ValueError:
        return None
    if st.get("BackendState") != "Running":
        return None
    return (st.get("Self", {}).get("DNSName") or "").rstrip(".") or None


def _tailscale_publicar(porta):
    """Publica 127.0.0.1:<porta> em https://<nome>.ts.net (só para a sua rede Tailscale)."""
    exe = tailscale_exe()
    saida = ""
    for args in ([exe, "serve", "--bg", "--https=443", f"http://127.0.0.1:{porta}"], [exe, "serve", "--bg", str(porta)]):
        codigo, saida = _rodar(args, timeout=12)
        if codigo == 0:
            return True, ""
        link = next((p for p in saida.split() if p.startswith("https://login.tailscale.com")), "")
        if link:          # 1ª vez: o recurso "Serve"/HTTPS precisa ser ligado na conta (o comando fica esperando)
            return False, ("falta ligar o recurso de acesso seguro do Tailscale, uma vez só. "
                           f"Abra {link} , clique em Enable e depois peça o QR de novo.")
        if codigo is None:
            break
    return False, f"o Tailscale não aceitou publicar o Ghost ({' '.join(saida.split())[:160] or 'sem resposta'})."


def _tailscale_despublicar():
    exe = tailscale_exe()
    if exe:
        try:
            _rodar([exe, "serve", "reset"])
        except Exception:
            pass


def categorias_de_rede():
    """Categorias das redes ativas do Windows: {"Private", "Public", "DomainAuthenticated"}."""
    if os.name != "nt":
        return set()
    try:
        _, saida = _rodar(["powershell", "-NoProfile", "-Command",
                           "(Get-NetConnectionProfile).NetworkCategory | ForEach-Object { $_.ToString() }"])
        return {linha.strip() for linha in saida.splitlines() if linha.strip()}
    except Exception:
        return set()


def rede_local_segura():
    cats = categorias_de_rede()
    return bool(cats) and cats <= REDES_PERMITIDAS


def ip_da_rede():
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))       # não envia nada: só descobre a interface de saída
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def _ligar_servidor(host):
    global _servidor
    _desligar_servidor()
    try:
        _servidor = ThreadingHTTPServer((host, PORTA), _RotasCelular)
    except OSError:
        _servidor = ThreadingHTTPServer((host, 0), _RotasCelular)
    _servidor.daemon_threads = True
    threading.Thread(target=_servidor.serve_forever, daemon=True, name="celular-servidor").start()
    return _servidor.server_address[1]


def _desligar_servidor():
    global _servidor
    if _servidor:
        _servidor.shutdown()
        _servidor.server_close()
        _servidor = None


def ativar(gerar_codigo=True):
    """Liga o acesso pelo celular. Devolve o que o painel mostra (QR, código, modo, avisos)."""
    global _modo, _base
    with _trava:
        aviso = ""
        nome = tailscale_nome()
        if nome:
            if _modo != "tailscale" or not _servidor:
                porta = _ligar_servidor("127.0.0.1")
                ok, msg = _tailscale_publicar(porta)
                if not ok:
                    _desligar_servidor()
                    _modo = _base = None
                    raise ErroCelular(msg)
                _modo, _base = "tailscale", f"https://{nome}"
        elif rede_local_segura():
            if _modo != "rede local" or not _servidor:
                porta = _ligar_servidor("0.0.0.0")
                _modo, _base = "rede local", f"http://{ip_da_rede()}:{porta}"
            aviso = ("Sem Tailscale: funciona só no mesmo Wi-Fi e sem criptografia. "
                     "Instale o Tailscale para usar no 5G com segurança.")
        else:
            _desligar_servidor()
            _modo = _base = None
            raise ErroCelular("Tailscale não está ligado e a rede atual do Windows não é Privada: "
                              "por segurança o acesso pelo celular ficou desligado.")
        preferencias.definir("celular_ativo", True)
        p = novo_codigo() if gerar_codigo else codigo_atual()
    resposta = {"modo": _modo, "aviso": aviso, "aparelhos": aparelhos(), "tem_pin": tem_pin(),
                "endereco": f"{_base}/celular"}
    if p:
        url = f"{_base}/parear?c={p['codigo']}"
        resposta.update(codigo=f"{p['codigo'][:3]} {p['codigo'][3:]}", expira_s=int(p["expira"] - time.time()),
                        qr_svg=qr_svg(url), endereco_qr=url)
    _evento(f"Acesso pelo celular ligado ({_modo})", "info")
    return resposta


def desativar():
    global _modo, _base, _pareamento
    with _trava:
        if _modo == "tailscale":
            _tailscale_despublicar()
        _desligar_servidor()
        _modo = _base = _pareamento = None
        _sessoes.clear()
    preferencias.definir("celular_ativo", False)
    _evento("Acesso pelo celular desligado", "info")


def situacao():
    return {"ativo": _servidor is not None, "modo": _modo, "aparelhos": aparelhos(), "tem_pin": tem_pin(),
            "tailscale_instalado": bool(tailscale_exe())}


def _vigiar_rede():
    """Rede local: se o PC passar para uma rede Pública (hotel, café), desliga o acesso na hora."""
    while True:
        time.sleep(60)
        try:
            if _modo == "rede local" and not rede_local_segura():
                desativar()
                preferencias.definir("celular_ativo", True)        # religa quando voltar para a rede segura
                _evento("Rede Pública detectada: acesso pelo celular desligado", "alerta")
            elif _modo is None and preferencias.carregar().get("celular_ativo") and (tailscale_nome() or rede_local_segura()):
                ativar(gerar_codigo=False)
        except Exception as e:
            print(f"\n[CELULAR]: {e!r}")


def qr_svg(texto):
    import io

    import segno
    buf = io.BytesIO()
    segno.make(texto, error="m").save(buf, kind="svg", scale=6, border=2, dark="#120d09", light="#f5ead6",
                                      xmldecl=False, svgns=True)
    return buf.getvalue().decode("utf-8")


def _evento(texto, tipo="info"):
    try:
        from ghost.nucleo import painel
        painel.evento(texto, tipo)
    except Exception:
        pass


def iniciar(entregar, avisar=None):
    """Chamado pelo Ghost na abertura. Religa o acesso se estava ligado (sem gerar código novo)."""
    global _entregar, _avisar
    _entregar, _avisar = entregar, avisar
    threading.Thread(target=_vigiar_rede, daemon=True, name="celular-rede").start()
    if preferencias.carregar().get("celular_ativo"):
        try:
            r = ativar(gerar_codigo=False)
            print(f"\n[CELULAR]: app em {r['endereco']} ({r['modo']}).")
        except ErroCelular as e:
            print(f"\n[CELULAR]: {e}")


# =============================================================
# 4. SERVIDOR DO CELULAR (só /celular, /parear e /api/*)
# =============================================================
PUBLICOS = {"nucleo.js": "text/javascript; charset=utf-8", "icone-192.png": "image/png", "icone-512.png": "image/png"}
PASTA_WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "painel_web")


def _foto_celular(aparelho):
    from ghost.nucleo import painel
    f = painel.foto()
    pendente = False
    try:
        from ghost.automacao import automacoes
        c = automacoes._confirmacao
        pendente = bool(c and time.time() - c["t"] <= automacoes.TEMPO_CONFIRMACAO)
    except Exception:
        pass
    return {"estado": f["estado"], "modo": f["modo"], "requisicoes": f["requisicoes"],
            "sistema": {k: f["sistema"].get(k) for k in ("cpu", "ram", "disco_livre_gb", "internet")},
            "celular": f["celular"], "confirmacao_pendente": pendente, "aparelho": aparelho["nome"]}


class _RotasCelular(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def _responder(self, codigo, corpo, tipo="application/json; charset=utf-8"):
        dados = corpo if isinstance(corpo, bytes) else json.dumps(corpo, ensure_ascii=False, default=str).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def _arquivo(self, nome):
        with open(os.path.join(PASTA_WEB, nome), "rb") as arq:
            return arq.read()

    def _aparelho(self):
        auth = self.headers.get("Authorization", "")
        return sessao(auth[7:].strip()) if auth.startswith("Bearer ") else None

    def _json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 10_000:
            raise ErroCelular("pedido grande demais")
        try:
            return json.loads(self.rfile.read(n) or b"{}") if n else {}
        except ValueError as e:
            raise ErroCelular("pedido inválido") from e

    def do_GET(self):
        rota = urlparse(self.path).path.lstrip("/")
        if rota in PUBLICOS:
            return self._responder(200, self._arquivo(rota), PUBLICOS[rota])
        if rota in ("", "celular", "parear"):
            html = self._arquivo("celular.html").replace(b"__GHOST_SERVIDOR__", b"1")
            return self._responder(200, html, "text/html; charset=utf-8")
        if rota == "manifest.webmanifest":
            return self._responder(200, {
                "name": "Ghost", "short_name": "Ghost", "lang": "pt-BR", "display": "standalone",
                "start_url": "/celular", "scope": "/", "background_color": "#0d0a08", "theme_color": "#0d0a08",
                "icons": [{"src": "icone-192.png", "sizes": "192x192", "type": "image/png"},
                          {"src": "icone-512.png", "sizes": "512x512", "type": "image/png"}]},
                "application/manifest+json; charset=utf-8")
        if rota == "api/estado":
            aparelho = self._aparelho()
            if not aparelho:
                return self._responder(401, {"erro": "sessao"})
            return self._responder(200, _foto_celular(aparelho))
        if rota == "api/imagem":
            if not self._aparelho():
                return self._responder(401, {"erro": "sessao"})
            from ghost.nucleo import painel
            ident = (parse_qs(urlparse(self.path).query).get("id") or [""])[0]
            dados = painel.imagem(ident) if re.fullmatch(r"[0-9a-f]{16}", ident) else None
            if not dados:
                return self._responder(404, {"erro": "imagem não está mais disponível"})
            return self._responder(200, dados, "image/jpeg")
        return self._responder(404, {"erro": "não encontrado"})

    def do_POST(self):
        rota = urlparse(self.path).path.lstrip("/")
        try:
            if rota == "api/parear":
                j = self._json()
                return self._responder(200, parear(j.get("codigo"), j.get("nome"), j.get("pin"), j.get("pin_confirmacao")))
            if rota == "api/entrar":
                j = self._json()
                return self._responder(200, entrar(j.get("aparelho_token"), j.get("pin")))
            if rota == "api/info":                     # a tela de pareamento sabe se precisa CRIAR o PIN
                return self._responder(200, {"tem_pin": tem_pin()})
            aparelho = self._aparelho()
            if not aparelho:
                return self._responder(401, {"erro": "sessao"})
            if rota == "api/sair":
                sair(self.headers.get("Authorization", "")[7:].strip())
                return self._responder(200, {"ok": True})
            if not _entregar:
                return self._responder(503, {"erro": "o Ghost ainda está iniciando"})
            from ghost.nucleo import painel
            if rota == "api/comando":
                texto = str(self._json().get("texto") or "").strip()[:500]
                if not texto:
                    return self._responder(400, {"erro": "pedido vazio"})
                painel.mensagem_celular("voce", texto)
                _entregar({"texto": texto, "origem": "celular", "aparelho": aparelho["nome"]})
                return self._responder(200, {"ok": True})
            if rota == "api/audio":
                n = int(self.headers.get("Content-Length") or 0)
                if not 0 < n <= MAX_AUDIO:
                    return self._responder(400, {"erro": "áudio vazio ou longo demais"})
                tipo = (self.headers.get("Content-Type") or "audio/webm").split(";")[0]
                extensao = {"audio/mp4": "m4a", "audio/x-m4a": "m4a", "audio/aac": "m4a", "audio/ogg": "ogg",
                            "audio/wav": "wav", "audio/mpeg": "mp3"}.get(tipo, "webm")
                _entregar({"audio": self.rfile.read(n), "nome_audio": f"celular.{extensao}", "origem": "celular",
                           "aparelho": aparelho["nome"]})
                return self._responder(200, {"ok": True})
            return self._responder(404, {"erro": "não encontrado"})
        except ErroCelular as e:
            return self._responder(400, {"erro": str(e)})
        except Exception as e:
            _evento(f"Celular: {rota} falhou ({e})", "erro")
            return self._responder(500, {"erro": "falha interna; veja o log do Ghost"})

