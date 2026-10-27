"""
GHOST - Rede da empresa, SOMENTE LEITURA. Um arquivo só para tudo de rede:
  1-4. inventário (varredura ARP/NetBIOS, apelidos, departamentos)   5. vigia (internet + aparelhos críticos)
  6. agentes MeshCentral (quem está logado, antivírus...)            7. dados do mapa "link neural"
  8. exportar para Excel                                               9. varredura automática

O que faz: descobre os aparelhos da rede local (ping + tabela ARP + nome NetBIOS/DNS), guarda um inventário
(dados/rede.json: MAC, IP, nome na rede, apelido, responsável, departamento, primeira e última vez visto) e
responde "quais máquinas estão ligadas", "a máquina do Gustavo está online?", "o que apareceu de novo",
"como está a internet". Uma varredura em segundo plano a cada INTERVALO_MIN avisa aparelho NOVO na rede.

O que NÃO faz: nada que altere outra máquina (sem desligar, reiniciar, instalar ou mexer em usuários).
Nomear uma máquina ("a 192.168.50.7 é do Gustavo, do TI") muda só o inventário do Ghost.
"""
import ipaddress
import json
import os
import re
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from ghost.nucleo import arquivo, caminhos

ARQUIVO = caminhos.dado("rede.json")
ARQ_DEPARTAMENTOS = caminhos.dado("rede_departamentos.json")
INTERVALO_MIN = 15            # varredura automática (minutos)
AVISAR_NOVOS = True           # fala quando aparece um aparelho nunca visto (MAC aleatório de celular não conta)
MAX_HOSTS = 1024              # nunca varre mais que isso (rede /22 ou menor)
ONLINE_S = 20 * 60            # visto nos últimos 20 min = ligado
SEM_JANELA = 0x08000000       # CREATE_NO_WINDOW

_trava = threading.Lock()
_ultima = {"t": 0.0, "duracao": 0.0, "rede": ""}


# =============================================================
# 1. FUNÇÕES PURAS (testáveis em qualquer sistema)
# =============================================================
def ler_arp(texto):
    """Saída do 'arp -a' -> {ip: mac}. Só entradas dinâmicas (pt/en); ignora broadcast e multicast."""
    saida = {}
    for linha in texto.splitlines():
        m = re.match(r"\s*(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F]{2}(?:[-:][0-9a-fA-F]{2}){5})\s+(\S+)", linha)
        if not m or not m.group(3).lower().startswith(("din", "dyn")):
            continue
        ip, mac = m.group(1), m.group(2).lower().replace(":", "-")
        if mac in ("ff-ff-ff-ff-ff-ff",) or mac.startswith("01-00-5e"):
            continue
        saida[ip] = mac
    return saida


def ler_nbtstat(texto):
    """Saída do 'nbtstat -A ip' -> (nome da máquina, grupo de trabalho). (None, None) se não respondeu."""
    nome = grupo = None
    for linha in texto.splitlines():
        m = re.match(r"\s*(\S[^<]*?)\s*<00>\s+(\S+)", linha)
        if not m:
            continue
        tipo = m.group(2).upper()
        if tipo in ("EXCLUSIVO", "UNIQUE", "ÚNICO", "UNICO") and not nome:
            nome = m.group(1).strip()
        elif tipo in ("GRUPO", "GROUP") and not grupo:
            grupo = m.group(1).strip()
    return nome, grupo


def mac_aleatorio(mac):
    """Celulares trocam o MAC sozinhos (bit 'local' ligado): não viram alerta de aparelho novo."""
    try:
        return bool(int(mac[:2], 16) & 0x02)
    except ValueError:
        return False


def normalizar(texto):
    import unicodedata
    t = unicodedata.normalize("NFD", (texto or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn").strip()


def nome_exibicao(a):
    return a.get("apelido") or a.get("nome") or "aparelho sem nome"


def procurar(inventario, termo):
    """Aparelhos cujo apelido, responsável, departamento, nome na rede, IP ou MAC contém o termo."""
    t = normalizar(termo)
    if not t:
        return []
    exato = [a for mac, a in inventario.items() if t in (a.get("ip"), mac, normalizar(a.get("nome")), normalizar(a.get("apelido")))]
    if exato:                                  # "192.168.50.1" não pode pegar também o .10, .11...
        return exato
    achados = []
    for mac, a in inventario.items():
        campos = [a.get("apelido"), a.get("responsavel"), a.get("departamento"), a.get("nome"), a.get("ip"), mac]
        if any(t in normalizar(c) for c in campos if c):
            achados.append(a)
    return achados


def online(a, agora=None):
    return (agora or time.time()) - a.get("ultima_vez", 0) <= ONLINE_S


# =============================================================
# 2. INVENTÁRIO
# =============================================================
def carregar():
    dados = arquivo.ler_json(ARQUIVO, {})
    return dados if isinstance(dados, dict) else {}


def _salvar(inv):
    arquivo.salvar_json(ARQUIVO, inv)


def mesclar(inv, achados, agora=None):
    """Junta uma varredura ao inventário. achados = {mac: {ip, nome, grupo, dns}}. Devolve os MACs novos."""
    agora = agora or time.time()
    novos = []
    for mac, info in achados.items():
        a = inv.get(mac)
        if a is None:
            a = inv[mac] = {"mac": mac, "primeira_vez": agora}
            novos.append(mac)
        a.update({k: v for k, v in info.items() if v})
        a["ultima_vez"] = agora
    return novos


def nomear(alvo, apelido=None, responsavel=None, departamento=None, critico=None):
    """Dá apelido/responsável/departamento a um aparelho (procurado por IP, MAC ou nome) e marca/desmarca como
    crítico (vigiado a cada minuto). Só muda o inventário do Ghost."""
    with _trava:
        inv = carregar()
        achados = procurar(inv, alvo)
        if len(achados) != 1:
            return None, len(achados)
        a = inv[achados[0]["mac"]]
        for campo, valor in (("apelido", apelido), ("responsavel", responsavel), ("departamento", departamento)):
            if valor:
                a[campo] = valor.strip()
        if critico is not None:
            a["critico"] = bool(critico)
        _salvar(inv)
        return a, 1


def editar(mac, campos):
    """Edição direta (tela do link neural): campos apelido/responsavel/departamento/critico; texto vazio apaga."""
    with _trava:
        inv = carregar()
        a = inv.get(mac)
        if a is None:
            return None
        for campo in ("apelido", "responsavel", "departamento"):
            if campo in campos:
                valor = str(campos[campo] or "").strip()[:60]
                if valor:
                    a[campo] = valor
                else:
                    a.pop(campo, None)
        if "critico" in campos:
            a["critico"] = bool(campos["critico"])
        _salvar(inv)
    if a.get("departamento"):
        definir_departamentos([a["departamento"]])
    return a


def atribuir_departamento(alvos, departamento):
    """Coloca vários aparelhos num departamento. Devolve (feitos, não achados, ambíguos)."""
    feitos, nao, amb = [], [], []
    with _trava:
        inv = carregar()
        for alvo in alvos:
            achados = procurar(inv, alvo)
            if len(achados) == 1:
                inv[achados[0]["mac"]]["departamento"] = departamento.strip()
                feitos.append(nome_exibicao(achados[0]))
            else:
                (nao if not achados else amb).append(alvo)
        _salvar(inv)
    definir_departamentos([departamento])
    return feitos, nao, amb


# ---- departamentos (existem mesmo sem aparelho, para aparecerem no mapa) ----
def departamentos():
    lista = arquivo.ler_json(ARQ_DEPARTAMENTOS, [])
    usados = {a.get("departamento") for a in carregar().values() if a.get("departamento")}
    vistos, saida = set(), []
    for d in list(lista if isinstance(lista, list) else []) + sorted(usados):
        if d and normalizar(d) not in vistos:
            vistos.add(normalizar(d))
            saida.append(d)
    return saida


def definir_departamentos(nomes, remover=False):
    """Cria (ou remove) departamentos. Nomes iguais sem acento/maiúscula contam como o mesmo."""
    with _trava:
        atual = arquivo.ler_json(ARQ_DEPARTAMENTOS, [])
        atual = atual if isinstance(atual, list) else []
        alvo = {normalizar(n) for n in nomes if n and n.strip()}
        if remover:
            atual = [d for d in atual if normalizar(d) not in alvo]
        else:
            existentes = {normalizar(d) for d in atual}
            atual += [n.strip() for n in nomes if n and n.strip() and normalizar(n) not in existentes]
        arquivo.salvar_json(ARQ_DEPARTAMENTOS, atual)
    return departamentos()


# =============================================================
# 3. VARREDURA (Windows)
# =============================================================
def _rodar(cmd, tempo=10):
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=tempo, creationflags=SEM_JANELA if os.name == "nt" else 0)
        return r.stdout.decode("cp850", errors="replace")
    except Exception:
        return ""


def minha_rede():
    """IPv4 local + rede (ex.: 192.168.50.37, 192.168.50.0/24) pela interface que tem gateway."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    finally:
        s.close()
    if _cache_rede.get("ip") != ip:            # o tamanho da rede só muda se o IP mudar: PowerShell 1 vez só
        texto = _rodar(["powershell", "-NoProfile", "-Command",
                        f"(Get-NetIPAddress -IPAddress {ip} -ErrorAction SilentlyContinue).PrefixLength"], 15).strip()
        prefixo = max(int(texto), 22) if texto.isdigit() else 24   # maior que /22: varre só a parte do IP (até 1024)
        _cache_rede.update(ip=ip, prefixo=prefixo)
    return ip, ipaddress.ip_network(f"{ip}/{_cache_rede['prefixo']}", strict=False)


_cache_rede = {}
_cache_gw = {"ip": None, "t": 0.0}


def gateway():
    """IP do roteador. Lido com 'route print' (leve) no máximo a cada 10 min; usado por todo o Ghost."""
    if _cache_gw["ip"] and time.time() - _cache_gw["t"] < 600:
        return _cache_gw["ip"]
    m = re.search(r"^\s*0\.0\.0\.0\s+0\.0\.0\.0\s+(\d+\.\d+\.\d+\.\d+)", _rodar(["route", "print", "-4", "0.0.0.0"], 5), re.M)
    if m:
        _cache_gw.update(ip=m.group(1), t=time.time())
    return _cache_gw["ip"]


def _ping(ip):
    _rodar(["ping", "-n", "1", "-w", "400", str(ip)], 3)


def _nome(ip):
    nome, grupo = ler_nbtstat(_rodar(["nbtstat", "-A", ip], 6))
    dns = None
    try:
        dns = socket.gethostbyaddr(ip)[0]
    except Exception:
        pass
    return {"nome": nome or (dns.split(".")[0] if dns else None), "grupo": grupo, "dns": dns}


def varrer():
    """Pinga a rede (preenche a tabela ARP mesmo de PCs que bloqueiam ping), lê o ARP e busca os nomes.
    Devolve (inventário atualizado, MACs novos)."""
    t0 = time.time()
    meu_ip, rede = minha_rede()
    hosts = list(rede.hosts())[:MAX_HOSTS]
    with ThreadPoolExecutor(64) as ex:
        list(ex.map(_ping, hosts))
    tabela = {ip: mac for ip, mac in ler_arp(_rodar(["arp", "-a"])).items() if ipaddress.ip_address(ip) in rede}
    with ThreadPoolExecutor(16) as ex:
        nomes = dict(zip(tabela, ex.map(_nome, tabela), strict=True))
    achados = {mac: {"ip": ip, **nomes[ip]} for ip, mac in tabela.items()}
    with _trava:
        inv = carregar()
        novos = mesclar(inv, achados)
        _salvar(inv)
    _ultima.update(t=time.time(), duracao=round(time.time() - t0, 1), rede=f"{rede} (este PC: {meu_ip})")
    return inv, novos


# =============================================================
# 4. RESPOSTAS (para a IA e para os comandos de voz)
# =============================================================
def _linha(a, agora):
    extra = ", ".join(x for x in (a.get("responsavel"), a.get("departamento"), "crítico" if a.get("critico") else None) if x)
    visto = "ligado" if online(a, agora) else f"visto por último {datetime.fromtimestamp(a.get('ultima_vez', 0)):%d/%m %H:%M}"
    return f"{nome_exibicao(a)} ({a.get('ip')}{', ' + extra if extra else ''}): {visto}"


def consultar(acao="listar", termo="", atualizar=True):
    """Texto com o resultado. acao: listar | procurar | novos | internet."""
    if acao == "internet":
        return internet()
    if atualizar and time.time() - _ultima["t"] > 120:
        varrer()
    inv, agora = carregar(), time.time()
    if acao == "procurar":
        achados = procurar(inv, termo)
        if not achados:
            return f"Nenhum aparelho do inventário corresponde a '{termo}'."
        return "\n".join(_linha(a, agora) for a in achados[:15])
    if acao == "novos":
        dia = agora - 24 * 3600
        novos = [a for a in inv.values() if a.get("primeira_vez", 0) >= dia]
        if not novos:
            return "Nenhum aparelho novo na rede nas últimas 24 horas."
        return "Aparelhos novos (24 h):\n" + "\n".join(_linha(a, agora) for a in novos[:20])
    ligados = sorted((a for a in inv.values() if online(a, agora)), key=lambda a: ipaddress.ip_address(a["ip"]))
    sem_nome = sum(1 for a in ligados if not a.get("apelido"))
    return (f"Rede {_ultima['rede']}: {len(ligados)} aparelhos ligados de {len(inv)} conhecidos "
            f"(varredura de {_ultima['duracao']}s). {sem_nome} ainda sem apelido.\n"
            + "\n".join(_linha(a, agora) for a in ligados[:40]))


def internet():
    """Latência até o roteador e até a internet (8.8.8.8 e 1.1.1.1)."""
    def medir(ip):
        texto = _rodar(["ping", "-n", "3", "-w", "1000", ip], 8)
        tempos = [int(x) for x in re.findall(r"[=<](\d+)\s*ms", texto)]
        return (round(sum(tempos) / len(tempos)), len(tempos)) if tempos else (None, 0)
    gw = gateway()
    partes = []
    for nome, ip in (("roteador", gw), ("Google DNS", "8.8.8.8"), ("Cloudflare", "1.1.1.1")):
        if not ip:
            continue
        ms, ok = medir(ip)
        partes.append(f"{nome} ({ip}): " + (f"{ms} ms, {ok}/3 respostas" if ms is not None else "sem resposta"))
    return "; ".join(partes)


# =============================================================
# 5. VIGIA: internet a cada minuto + aparelhos marcados como críticos (avisa queda e volta)
# =============================================================
ARQ_INTERNET = caminhos.dado("internet.jsonl")
ARQ_EVENTOS = caminhos.dado("rede_eventos.jsonl")
CICLO_S = 60
FALHAS_PARA_ALERTA = 2        # 2 minutos fora do ar
RETENCAO_DIAS = 90
ALVOS_INTERNET = ("8.8.8.8", "1.1.1.1")
PORTAS = (445, 80, 443, 9100, 554, 3389, 22, 8080)
AVISO_SEM_INTERNET = "Senhor, estou sem internet no momento."   # igual a app.AVISO_SEM_INTERNET (cache de voz)

_ultima_internet = {}         # último teste (o painel lê daqui em vez de medir de novo)
_estado_vigia = {}                  # chave -> {"falhas", "fora_desde", "avisado"}
_trava_vigia = threading.Lock()


# =============================================================
# 5.1 TESTES
# =============================================================
def _ping_ms(ip, tempo_ms=1000):
    """Latência em ms (int) ou None."""
    try:
        r = subprocess.run(["ping", "-n", "1", "-w", str(tempo_ms), ip], capture_output=True, timeout=tempo_ms / 1000 + 3,
                           creationflags=SEM_JANELA if os.name == "nt" else 0)
        m = re.search(r"[=<](\d+)\s*ms", r.stdout.decode("cp850", errors="replace"))
        return int(m.group(1)) if m and r.returncode == 0 else None
    except Exception:
        return None


def _porta_responde(ip, porta, tempo=1.0):
    """True se o aparelho respondeu na porta (aceitou OU recusou: os dois provam que está ligado)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(tempo)
    try:
        return s.connect_ex((ip, porta)) in (0, 10061, 111)      # 0 = aberta; 10061/111 = recusada
    except OSError:
        return False
    finally:
        s.close()


def _tcp_ms(ip, porta, tempo=1.5):
    """Latência de uma conexão TCP em ms (sem abrir processo, ao contrário do ping.exe), ou None."""
    t0 = time.perf_counter()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(tempo)
    try:
        return round((time.perf_counter() - t0) * 1000) if s.connect_ex((ip, porta)) in (0, 10061, 111) else None
    except OSError:
        return None
    finally:
        s.close()


def responde(ip):
    """Ligado? Primeiro portas comuns (leve, sem processo); o ping.exe só se nenhuma responder."""
    if any(_porta_responde(ip, p, 0.5) for p in PORTAS):
        return True
    return _ping_ms(ip) is not None


# =============================================================
# 5.2 TRANSIÇÕES (função pura: decide quando avisar)
# =============================================================
def registrar_teste(chave, ok, agora, estado=None):
    """Atualiza o estado de um alvo. Devolve ('caiu', None) | ('voltou', minutos_fora) | (None, None)."""
    estado = _estado_vigia if estado is None else estado
    e = estado.setdefault(chave, {"falhas": 0, "fora_desde": None, "avisado": False})
    if ok:
        avisado, desde = e["avisado"], e["fora_desde"]
        e.update(falhas=0, fora_desde=None, avisado=False)
        if avisado:
            return "voltou", round((agora - desde) / 60)
        return None, None
    e["falhas"] += 1
    if e["fora_desde"] is None:
        e["fora_desde"] = agora
    if e["falhas"] >= FALHAS_PARA_ALERTA and not e["avisado"]:
        e["avisado"] = True
        return "caiu", None
    return None, None


# =============================================================
# 5.3 RESUMO DO HISTÓRICO (função pura)
# =============================================================
def resumir_internet(linhas, desde, ate=None):
    """linhas = registros de internet.jsonl. Devolve dict com disponibilidade, latência média e quedas."""
    ate = ate or time.time()
    reg = [r for r in linhas if desde <= r.get("t", 0) <= ate]
    if not reg:
        return None
    ok = [r for r in reg if r.get("net_ms") is not None]
    quedas, inicio, causa = [], None, None
    for r in reg:
        if r.get("net_ms") is None:
            if inicio is None:
                inicio = r["t"]
                causa = "rede interna/roteador" if r.get("gw_ms") is None else "provedor de internet"
        elif inicio is not None:
            quedas.append({"inicio": inicio, "fim": r["t"], "min": max(1, round((r["t"] - inicio) / 60)), "causa": causa})
            inicio = None
    if inicio is not None:
        quedas.append({"inicio": inicio, "fim": None, "min": max(1, round((reg[-1]["t"] - inicio) / 60)), "causa": causa})
    lat = [r["net_ms"] for r in ok]
    return {"testes": len(reg), "disponibilidade": round(100 * len(ok) / len(reg), 2),
            "latencia_media": round(sum(lat) / len(lat)) if lat else None,
            "latencia_max": max(lat) if lat else None, "quedas": quedas}


def texto_internet(periodo="hoje"):
    agora = time.time()
    hoje = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    desde = {"hoje": hoje, "24h": agora - 86400, "semana": agora - 7 * 86400, "mes": agora - 30 * 86400}.get(periodo, hoje)
    r = resumir_internet(arquivo.ler_jsonl(ARQ_INTERNET), desde, agora)
    if not r:
        return "Ainda não há histórico da internet para esse período (o Ghost registra a cada minuto enquanto está aberto)."
    q = r["quedas"]
    linhas = [f"Internet ({periodo}): {r['disponibilidade']}% do tempo no ar, latência média {r['latencia_media']} ms "
              f"(máx. {r['latencia_max']} ms), {len(q)} queda(s) em {r['testes']} testes."]
    for x in q[-8:]:
        fim = f"{datetime.fromtimestamp(x['fim']):%H:%M}" if x["fim"] else "agora"
        linhas.append(f"- {datetime.fromtimestamp(x['inicio']):%d/%m %H:%M} a {fim}: {x['min']} min ({x['causa']})")
    return "\n".join(linhas)


def eventos_recentes(dias=7):
    desde = time.time() - dias * 86400
    ev = [e for e in arquivo.ler_jsonl(ARQ_EVENTOS) if e.get("t", 0) >= desde]
    if not ev:
        return f"Nenhuma queda de aparelho crítico nos últimos {dias} dias."
    return "\n".join(f"- {datetime.fromtimestamp(e['t']):%d/%m %H:%M}: {e['nome']} {e['tipo']}"
                     + (f" ({e['min']} min fora)" if e.get("min") else "") for e in ev[-15:])


# =============================================================
# 5.4 LAÇO
# =============================================================
def _podar(caminho, dias):
    """Mantém só os últimos `dias` dias (roda 1x por dia)."""
    limite = time.time() - dias * 86400
    itens = arquivo.ler_jsonl(caminho)
    if itens and itens[0].get("t", 0) < limite:
        manter = [i for i in itens if i.get("t", 0) >= limite]
        tmp = caminho + ".tmp"
        import json
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(json.dumps(i, ensure_ascii=False) + "\n" for i in manter)
        os.replace(tmp, caminho)


def ultima_internet():
    return dict(_ultima_internet)


def ciclo_vigia(falar=None):
    """Um teste completo. Devolve o registro da internet."""
    agora = time.time()
    gw = gateway()
    gw_ms = (_tcp_ms(gw, 80) or _ping_ms(gw)) if gw else None      # roteador: porta da página dele; senão ping
    net_ok = [x for x in (_tcp_ms(ip, 443) for ip in ALVOS_INTERNET) if x is not None]
    reg = {"t": round(agora), "gw_ms": gw_ms, "net_ms": min(net_ok) if net_ok else None}
    _ultima_internet.update(reg)
    arquivo.acrescentar_jsonl(ARQ_INTERNET, reg)

    alvos = [("internet", "A internet", reg["net_ms"] is not None)]
    if gw:
        alvos.append(("roteador", "O roteador", gw_ms is not None))
    for a in carregar().values():
        if a.get("critico") and a.get("ip"):
            alvos.append((a["mac"], nome_exibicao(a), responde(a["ip"])))
    for chave, nome, ok in alvos:
        with _trava_vigia:
            tipo, minutos = registrar_teste(chave, ok, agora)
        if not tipo:
            continue
        arquivo.acrescentar_jsonl(ARQ_EVENTOS, {"t": round(agora), "nome": nome, "tipo": tipo, "min": minutos})
        msg = (f"Senhor, {nome.lower() if chave in ('internet', 'roteador') else nome} caiu: sem resposta há "
               f"{FALHAS_PARA_ALERTA} minutos." if tipo == "caiu"
               else f"Senhor, {nome.lower() if chave in ('internet', 'roteador') else nome} voltou, depois de {minutos} minutos fora.")
        if chave == "internet" and tipo == "caiu":
            msg = AVISO_SEM_INTERNET          # frase guardada no cache de voz: sem internet não dá para gerar outra
        print(f"\n[REDE]: {msg}")
        try:
            from ghost.nucleo import painel
            painel.evento(msg.replace("Senhor, ", ""), "alerta" if tipo == "caiu" else "info")
        except Exception:
            pass
        if falar:
            falar(msg)
    return reg


def iniciar_vigia(falar=None, ocupado=None):
    def laco():
        podado = 0.0
        while True:
            try:
                ciclo_vigia(falar)
                if time.time() - podado > 86400:
                    _podar(ARQ_INTERNET, RETENCAO_DIAS)
                    _podar(ARQ_EVENTOS, 365)
                    podado = time.time()
            except Exception as e:
                print(f"\n[REDE]: vigia falhou ({e!r}).")
            time.sleep(CICLO_S)
    threading.Thread(target=laco, daemon=True, name="vigia-rede").start()


# =============================================================
# 6. AGENTES MESHCENTRAL (somente leitura, conta "ghost" sem controle remoto; dados no .env:
#    MESH_URL, MESH_USUARIO, MESH_SENHA e, opcional, MESH_CTRL = caminho do meshctrl.js)
# =============================================================
MESHCTRL_PADRAO = r"C:\MeshCentral\node_modules\meshcentral\meshctrl.js"
CACHE_MESH_S = 120              # o mapa atualiza a cada 30 s; o Node (meshctrl) só roda a cada 2 min

_cache_mesh = {"t": 0.0, "dados": None, "erro": None, "t_erro": 0.0}
ESPERA_APOS_ERRO_S = 60       # MeshCentral fora do ar: não tenta de novo a cada pedido (cada tentativa leva ~10 s)


class SemMesh(Exception):
    """MeshCentral não configurado ou fora do ar (mensagem pronta para o usuário)."""


# =============================================================
# 6.1 LEITURA
# =============================================================
def mesh_configurado():
    return all(os.getenv(k) for k in ("MESH_URL", "MESH_USUARIO", "MESH_SENHA"))


def listar_agentes(forcar=False):
    """Lista crua de dispositivos (dicts do MeshCentral). Cache de CACHE_MESH_S segundos."""
    if not forcar and _cache_mesh["dados"] is not None and time.time() - _cache_mesh["t"] < CACHE_MESH_S:
        return _cache_mesh["dados"]
    if not forcar and _cache_mesh["erro"] and time.time() - _cache_mesh["t_erro"] < ESPERA_APOS_ERRO_S:
        raise SemMesh(_cache_mesh["erro"])
    try:
        return _ler_agentes()
    except SemMesh as e:
        _cache_mesh.update(erro=str(e), t_erro=time.time())
        raise


def _ler_agentes():
    if not mesh_configurado():
        raise SemMesh("o MeshCentral não está configurado no .env (MESH_URL, MESH_USUARIO, MESH_SENHA)")
    saida = _meshctrl(["ListDevices", "--json"], "MESH_USUARIO", "MESH_SENHA")
    try:
        dados = json.loads(saida)
    except ValueError as e:
        linhas = saida.strip().splitlines()
        raise SemMesh("o MeshCentral recusou ou está fora do ar" + (f" ({linhas[-1][:120]})" if linhas else "")) from e
    _cache_mesh.update(t=time.time(), dados=dados, erro=None)
    return dados


def _meshctrl(argumentos, var_usuario, var_senha, tempo=40):
    """Roda o meshctrl.js com a conta indicada no .env. Devolve a saída (senha nunca aparece)."""
    usuario, senha = os.getenv(var_usuario), os.getenv(var_senha)
    if not (os.getenv("MESH_URL") and usuario and senha):
        raise SemMesh(f"falta no .env: MESH_URL, {var_usuario} e {var_senha}")
    ctrl = os.getenv("MESH_CTRL") or MESHCTRL_PADRAO
    if not os.path.exists(ctrl):
        raise SemMesh(f"não achei o meshctrl.js em {ctrl}")
    cmd = ["node", ctrl, *argumentos, "--url", os.environ["MESH_URL"], "--loginuser", usuario, "--loginpass", senha]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=tempo,
                           creationflags=SEM_JANELA if os.name == "nt" else 0)
    except subprocess.TimeoutExpired as e:
        raise SemMesh("o MeshCentral não respondeu (o serviço está rodando?)") from e
    return (r.stdout + r.stderr).replace(senha, "***")


# =============================================================
# 6.2 RESUMO (função pura)
# =============================================================
def resumo_agente(d):
    """Dispositivo cru -> dict simples. Só campos de inventário e segurança."""
    wsc = d.get("wsc") or {}
    av = d.get("av") or []
    boot = d.get("lastbootuptime")
    return {
        "nome": d.get("name") or d.get("rname"),
        "ip": d.get("ip") or d.get("host"),
        "ligado": bool((d.get("conn") or 0) & 1),
        "usuarios": [u.split("\\")[-1] for u in (d.get("users") or [])],
        "ligado_desde": datetime.fromtimestamp(boot / 1000) if boot else None,
        "sistema": d.get("osdesc"),
        "antivirus": ", ".join(f"{a.get('product')} {'ativo' if a.get('enabled') else 'DESLIGADO'}"
                               f"{'' if a.get('updated', True) else ' (desatualizado)'}" for a in av) or None,
        "antivirus_ok": wsc.get("antiVirus", "OK") == "OK" and all(a.get("enabled") for a in av),
        "firewall_ok": wsc.get("firewall", "OK") == "OK",
        "atualizacao_ok": wsc.get("autoUpdate", "OK") == "OK",
        "reinicio_pendente": bool(d.get("pr")),
        "grupo": d.get("groupname"),
        "id": d.get("_id"),
    }


def problemas_agente(r):
    """Lista de problemas de segurança/manutenção de uma máquina resumida."""
    p = []
    if not r["antivirus_ok"]:
        p.append("antivírus com problema")
    if not r["firewall_ok"]:
        p.append("firewall com alerta")
    if not r["atualizacao_ok"]:
        p.append("atualização automática com problema")
    if r["reinicio_pendente"]:
        p.append("reinício pendente")
    return p


def _apelido_agente(r, inventario):
    """Junta o apelido/responsável do inventário da rede (pelo IP)."""
    a = next((x for x in inventario.values() if x.get("ip") == r["ip"]), None)
    if not a:
        return r["nome"]
    extra = ", ".join(x for x in (a.get("responsavel"), a.get("departamento")) if x)
    return f"{a.get('apelido') or r['nome']}" + (f" ({extra})" if extra else "")


def texto_agentes(lista, inventario, acao="listar", termo=""):
    rs = [resumo_agente(d) for d in lista]
    if acao == "procurar":
        t = (termo or "").lower()
        rs = [r for r in rs if t in (r["nome"] or "").lower() or t in (r["ip"] or "") or t in " ".join(r["usuarios"]).lower()
              or t in _apelido_agente(r, inventario).lower()]
        if not rs:
            return f"Nenhuma máquina com agente corresponde a '{termo}'."
    if acao == "alertas":
        com = [(r, problemas_agente(r)) for r in rs]
        com = [(r, p) for r, p in com if p] + [(r, ["desligada"]) for r in rs if not r["ligado"]]
        if not com:
            return f"Nenhum alerta nas {len(rs)} máquinas com agente: antivírus, firewall e atualizações em ordem."
        return "\n".join(f"{_apelido_agente(r, inventario)}: {', '.join(p)}" for r, p in com)
    linhas = []
    for r in rs:
        if not r["ligado"]:
            linhas.append(f"{_apelido_agente(r, inventario)} ({r['ip']}): desligada ou sem agente conectado")
            continue
        desde = f", ligada desde {r['ligado_desde']:%d/%m %H:%M}" if r["ligado_desde"] else ""
        quem = f", logado: {', '.join(r['usuarios'])}" if r["usuarios"] else ", ninguém logado"
        p = problemas_agente(r)
        linhas.append(f"{_apelido_agente(r, inventario)} ({r['ip']}){quem}{desde}; {r['sistema']}; antivírus: {r['antivirus']}"
                      + (f"; ATENÇÃO: {', '.join(p)}" if p else "; segurança em ordem"))
    return f"{len(rs)} máquina(s) com agente:\n" + "\n".join(linhas)


def consultar_agentes(acao="listar", termo=""):
    try:
        lista = listar_agentes()
    except SemMesh as e:
        return f"Não consegui consultar as máquinas: {e}."
    return texto_agentes(lista, carregar(), acao, termo)


# =============================================================
# 7. DADOS DO MAPA "LINK NEURAL" (painel_web/hud_rede.html)
# =============================================================
def tipo_aparelho(a, gateway=None):
    """Palpite do tipo pelo IP/nome (sem consultar nada): roteador, servidor, impressora, camera, computador, desconhecido."""
    nome = f"{a.get('apelido') or ''} {a.get('nome') or ''}".upper()
    if gateway and a.get("ip") == gateway:
        return "roteador"
    if re.search(r"SERVIDOR|SERVER|\bSRV|NAS\b", nome):
        return "servidor"
    if re.search(r"IMP|PRINT|NPI[0-9A-F]{6}|^ *SEC[0-9A-F]{12}|EPSON|BROTHER|HP[0-9A-F]{6}", nome):
        return "impressora"
    if re.search(r"CAM|DVR|NVR|INTELBRAS|HIKVISION", nome):
        return "camera"
    if nome.strip():
        return "computador"
    return "desconhecido"


GRUPO_DO_TIPO = {"computador": "Sem departamento", "desconhecido": "Não identificados", "servidor": "Servidores",
                 "impressora": "Impressoras", "camera": "Câmeras", "roteador": "Roteador"}
def dados_mapa():
    """Tudo o que o mapa da rede desenha: internet, roteador, aparelhos (com grupo, tipo, estado) e agentes."""
    agora = time.time()
    inv = carregar()
    ultima = (arquivo.ler_jsonl(ARQ_INTERNET) or [{}])[-1]
    gw = gateway()
    agentes = {}
    try:
        if mesh_configurado():
            for d in listar_agentes():
                r = resumo_agente(d)
                agentes[r["ip"]] = {"id": r["id"], "logado": r["usuarios"], "sistema": r["sistema"], "antivirus": r["antivirus"],
                                    "problemas": problemas_agente(r), "ligado_desde": str(r["ligado_desde"] or "")}
    except Exception:
        pass
    quedas = {k for k, e in _estado_vigia.items() if e.get("avisado")}
    aparelhos = []
    for mac, a in inv.items():
        tipo = tipo_aparelho(a, gw)
        aparelhos.append({
            "id": mac, "nome": nome_exibicao(a), "nome_rede": a.get("nome"), "apelido": a.get("apelido"),
            "responsavel": a.get("responsavel"), "departamento": a.get("departamento"), "ip": a.get("ip"), "mac": mac,
            "grupo_trabalho": a.get("grupo"), "tipo": tipo,
            "grupo": a.get("departamento") or GRUPO_DO_TIPO.get(tipo, "Outros"),
            "ligado": online(a, agora), "critico": bool(a.get("critico")), "fora_do_ar": mac in quedas,
            "novo": agora - a.get("primeira_vez", 0) < 86400, "primeira_vez": a.get("primeira_vez"),
            "ultima_vez": a.get("ultima_vez"), "agente": agentes.get(a.get("ip")), "agendada": agendada(mac),
        })
    mesh_web = re.sub(r"^wss?://", "https://", os.getenv("MESH_URL", "")).rstrip("/") or None
    return {"gerado": agora, "gateway": gw, "departamentos": departamentos(), "mesh_web": mesh_web,
            "acoes_mesh": bool(os.getenv("MESH_ACAO_USUARIO") and os.getenv("MESH_ACAO_SENHA")),
            "internet": {"ok": ultima.get("net_ms") is not None if ultima else None, "ms": ultima.get("net_ms"),
                         "roteador_ms": ultima.get("gw_ms"), "quando": ultima.get("t"), "fora": "internet" in quedas},
            "aparelhos": aparelhos}


# =============================================================
# 8. EXPORTAR PARA EXCEL
# =============================================================
PASTA_EXPORTAR = os.path.join(os.path.expanduser("~"), "Documents", "Ghost", "Relatorios")


def exportar():
    """Excel com o inventário, as quedas dos aparelhos críticos e o histórico diário da internet. Devolve o caminho."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    inv, agora = carregar(), time.time()
    os.makedirs(PASTA_EXPORTAR, exist_ok=True)
    caminho = os.path.join(PASTA_EXPORTAR, f"Rede_{datetime.now():%Y-%m-%d_%H%M}.xlsx")
    wb = Workbook()
    cab, fundo = Font(bold=True, color="FFF4E6"), PatternFill("solid", fgColor="7A2E0E")

    def aba(ws, titulo, colunas, linhas, larguras):
        ws.title = titulo
        ws.append(colunas)
        for c in ws[1]:
            c.font, c.fill = cab, fundo
        for linha in linhas:
            ws.append(linha)
        for i, w in enumerate(larguras):
            ws.column_dimensions[chr(65 + i)].width = w
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions

    data = lambda t: datetime.fromtimestamp(t) if t else None  # noqa: E731
    ordem = sorted(inv.values(), key=lambda a: ipaddress.ip_address(a.get("ip", "0.0.0.0")))
    aba(wb.active, "Inventário",
        ["Apelido", "Responsável", "Departamento", "Nome na rede", "Grupo", "IP", "MAC", "Crítico", "Situação",
         "Primeira vez", "Última vez"],
        [[a.get("apelido"), a.get("responsavel"), a.get("departamento"), a.get("nome"), a.get("grupo"), a.get("ip"),
          a.get("mac"), "sim" if a.get("critico") else "", "ligado" if online(a, agora) else "desligado",
          data(a.get("primeira_vez")), data(a.get("ultima_vez"))] for a in ordem],
        [22, 18, 18, 20, 12, 15, 19, 8, 11, 17, 17])
    eventos = arquivo.ler_jsonl(ARQ_EVENTOS)
    aba(wb.create_sheet(), "Quedas", ["Quando", "Aparelho", "Evento", "Minutos fora"],
        [[data(e["t"]), e.get("nome"), e.get("tipo"), e.get("min")] for e in reversed(eventos)], [17, 26, 10, 12])
    linhas = arquivo.ler_jsonl(ARQ_INTERNET)
    dias = sorted({datetime.fromtimestamp(r["t"]).date() for r in linhas}, reverse=True)
    diario = []
    for d in dias:
        ini = datetime.combine(d, datetime.min.time()).timestamp()
        r = resumir_internet(linhas, ini, ini + 86400 - 1)
        if r:
            diario.append([d, r["disponibilidade"], r["latencia_media"], r["latencia_max"], len(r["quedas"]),
                           sum(q["min"] for q in r["quedas"]), r["testes"]])
    aba(wb.create_sheet(), "Internet por dia",
        ["Dia", "No ar (%)", "Latência média (ms)", "Latência máx. (ms)", "Quedas", "Minutos fora", "Testes"],
        diario, [12, 10, 18, 17, 8, 13, 8])
    wb.save(caminho)
    return caminho


# =============================================================
# 9. VARREDURA AUTOMÁTICA
# =============================================================
def iniciar(falar=None, ocupado=None):
    def laco():
        primeira = not carregar()            # 1ª vez: só aprende a rede, sem avisar 30 "novos"
        ultimo_erro = None
        while True:
            try:
                inv, novos = varrer()
                avisar = [inv[m] for m in novos if not mac_aleatorio(m)]
                if avisar and AVISAR_NOVOS and not primeira and falar and not (ocupado and ocupado()):
                    nomes = ", ".join(f"{nome_exibicao(a)} ({a.get('ip')})" for a in avisar[:3])
                    falar(f"Senhor, apareceu {'um aparelho novo' if len(avisar) == 1 else f'{len(avisar)} aparelhos novos'}"
                          f" na rede: {nomes}.")
                try:
                    from ghost.nucleo import painel
                    painel.evento(f"Rede: {sum(1 for a in inv.values() if online(a))} ligados"
                                  + (f", {len(novos)} novo(s)" if novos else ""), "alerta" if avisar else "info")
                except Exception:
                    pass
                primeira = False
            except Exception as e:
                if repr(e) != ultimo_erro:            # sem rede (PC suspenso): registra uma vez, não a cada 15 min
                    print(f"\n[REDE]: varredura falhou ({e!r}).")
                ultimo_erro = repr(e)
            else:
                ultimo_erro = None
            time.sleep(INTERVALO_MIN * 60)
    threading.Thread(target=laco, daemon=True, name="rede").start()


# =============================================================
# 10. AÇÕES NOS EQUIPAMENTOS — SÓ PELO PAINEL (botões do link neural), NUNCA pela IA ou por voz.
#     Lista fechada; cada ação vai para o log e para os eventos do painel.
#     Conta do MeshCentral SÓ para ações (.env): MESH_ACAO_USUARIO / MESH_ACAO_SENHA
#     (permissões no grupo: "Ações de energia" e "Chat e notificação"; nada de área de trabalho/terminal/arquivos).
# =============================================================
AVISO_ANTES_S = 120                       # reiniciar/desligar: avisa na tela e espera 2 min (dá para cancelar)
_agendadas = {}                           # mac -> {"acao", "quando", "timer"}


def pacote_wol(mac):
    """Pacote mágico do Wake-on-LAN: 6 x FF + 16 x o MAC (função pura)."""
    b = bytes.fromhex(re.sub(r"[^0-9a-fA-F]", "", mac))
    if len(b) != 6:
        raise ValueError(f"MAC inválido: {mac}")
    return b"\xff" * 6 + b * 16


def ligar_wol(mac):
    """Liga um PC pela rede (precisa do Wake-on-LAN ativo na placa/BIOS dele). Não precisa de agente."""
    pacote = pacote_wol(mac)
    _, rede_local = minha_rede()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for destino in {"255.255.255.255", str(rede_local.broadcast_address)}:
            for porta in (9, 7):
                s.sendto(pacote, (destino, porta))
    return "pacote de ligar enviado (se o Wake-on-LAN estiver ativo no PC, ele liga em até 1 minuto)"


def _agente_do(a):
    """Id do agente MeshCentral do aparelho (pelo IP), ou erro claro."""
    for d in listar_agentes():
        r = resumo_agente(d)
        if r["ip"] == a.get("ip") and r["id"]:
            return r["id"], r["ligado"]
    raise SemMesh(f"{nome_exibicao(a)} não tem o agente do MeshCentral instalado")


def _mesh_acao(argumentos):
    saida = _meshctrl(argumentos, "MESH_ACAO_USUARIO", "MESH_ACAO_SENHA", tempo=60)
    if re.search(r"(?i)\b(error|erro|denied|negad|invalid|not found|failed)\b", saida):
        raise SemMesh(saida.strip().splitlines()[-1][:160])
    return saida


def _executar_energia(mac, acao):
    _agendadas.pop(mac, None)
    a = carregar().get(mac) or {}
    try:
        no, _ = _agente_do(a)
        _mesh_acao(["DevicePower", "--reset" if acao == "reiniciar" else "--off", "--id", no])
        _registrar_acao(a, f"{acao} executado")
    except Exception as e:
        _registrar_acao(a, f"{acao} FALHOU: {e}")


def _registrar_acao(a, texto):
    msg = f"Rede: {nome_exibicao(a)} ({a.get('ip')}): {texto}"
    print(f"\n[AÇÃO MANUAL]: {msg}")
    try:
        from ghost.nucleo import painel
        painel.evento(msg, "acao")
    except Exception:
        pass


def acao_manual(mac, acao, texto=""):
    """Ponto único das ações do painel. acao: ligar | mensagem | reiniciar | desligar | cancelar."""
    a = carregar().get(mac)
    if a is None:
        raise ValueError("aparelho não está no inventário")
    if acao == "ligar":
        r = ligar_wol(mac)
    elif acao == "mensagem":
        texto = (texto or "").strip()[:300]
        if not texto:
            raise ValueError("mensagem vazia")
        no, ligado = _agente_do(a)
        if not ligado:
            raise ValueError("o agente desse PC está desconectado")
        _mesh_acao(["DeviceMessage", "--id", no, "--msg", texto, "--title", "Aviso do TI"])
        r = "mensagem mostrada na tela"
    elif acao in ("reiniciar", "desligar"):
        if mac in _agendadas:
            raise ValueError(f"já há um '{_agendadas[mac]['acao']}' agendado; cancele antes")
        no, ligado = _agente_do(a)
        if not ligado:
            raise ValueError("o agente desse PC está desconectado")
        minutos = AVISO_ANTES_S // 60
        _mesh_acao(["DeviceMessage", "--id", no, "--title", "Aviso do TI", "--timeout", str(AVISO_ANTES_S * 1000),
                    "--msg", f"Este computador vai {'REINICIAR' if acao == 'reiniciar' else 'DESLIGAR'} em {minutos} "
                             "minutos. Salve o que estiver fazendo."])
        t = threading.Timer(AVISO_ANTES_S, _executar_energia, args=(mac, acao))
        t.daemon = True
        _agendadas[mac] = {"acao": acao, "quando": time.time() + AVISO_ANTES_S, "timer": t}
        t.start()
        r = f"aviso mostrado na tela; {acao} em {minutos} minutos (dá para cancelar)"
    elif acao == "cancelar":
        ag = _agendadas.pop(mac, None)
        if not ag:
            raise ValueError("não há nada agendado para esse PC")
        ag["timer"].cancel()
        try:
            no, _ = _agente_do(a)
            _mesh_acao(["DeviceMessage", "--id", no, "--title", "Aviso do TI", "--msg",
                        f"O {'reinício' if ag['acao'] == 'reiniciar' else 'desligamento'} foi cancelado."])
        except Exception:
            pass
        r = f"{ag['acao']} cancelado"
    else:
        raise ValueError("ação não permitida")
    _registrar_acao(a, r)
    return r


def agendada(mac):
    ag = _agendadas.get(mac)
    return {"acao": ag["acao"], "faltam_s": max(0, round(ag["quando"] - time.time()))} if ag else None


# =============================================================
# 11. IMPRESSORAS: toner, papel e erros por SNMP (SOMENTE LEITURA; sem biblioteca extra)
# =============================================================
SNMP_COMUNIDADE = "public"
OID_DESCRICAO = "1.3.6.1.2.1.1.1.0"
OID_STATUS = "1.3.6.1.2.1.25.3.5.1.1.1"           # hrPrinterStatus: 3 parada, 4 imprimindo, 5 aquecendo
OID_ERROS = "1.3.6.1.2.1.25.3.5.1.2.1"            # hrPrinterDetectedErrorState (bits)
OID_SUPRIMENTO_NOME = "1.3.6.1.2.1.43.11.1.1.6.1"
OID_SUPRIMENTO_MAX = "1.3.6.1.2.1.43.11.1.1.8.1"
OID_SUPRIMENTO_NIVEL = "1.3.6.1.2.1.43.11.1.1.9.1"
ERROS_IMPRESSORA = ["pouco papel", "sem papel", "pouco toner", "sem toner", "porta aberta", "papel atolado",
                    "offline", "precisa de manutenção", "bandeja de entrada ausente", "bandeja de saída ausente",
                    "suprimento ausente", "saída quase cheia", "saída cheia", "bandeja vazia", "manutenção atrasada"]


def _ber_tamanho(n):
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def _ber(tag, conteudo):
    return bytes([tag]) + _ber_tamanho(len(conteudo)) + conteudo


def _ber_int(v):
    return _ber(0x02, v.to_bytes(max(1, (v.bit_length() + 8) // 8), "big", signed=True))


def _ber_oid(oid):
    p = [int(x) for x in oid.split(".")]
    corpo = bytes([40 * p[0] + p[1]])
    for n in p[2:]:
        partes = [n & 0x7F]
        n >>= 7
        while n:
            partes.insert(0, 0x80 | (n & 0x7F))
            n >>= 7
        corpo += bytes(partes)
    return _ber(0x06, corpo)


def snmp_pedido(oid, proximo=False, comunidade=SNMP_COMUNIDADE, req=1):
    """Monta um GET (ou GETNEXT) SNMP v1 (função pura)."""
    vb = _ber(0x30, _ber(0x30, _ber_oid(oid) + b"\x05\x00"))
    pdu = _ber(0xA1 if proximo else 0xA0, _ber_int(req) + _ber_int(0) + _ber_int(0) + vb)
    return _ber(0x30, _ber_int(0) + _ber(0x04, comunidade.encode()) + pdu)


def _ler_tlv(dados, i):
    tag, n = dados[i], dados[i + 1]
    i += 2
    if n & 0x80:
        k = n & 0x7F
        n = int.from_bytes(dados[i:i + k], "big")
        i += k
    return tag, dados[i:i + n], i + n


def _oid_texto(b):
    p = [b[0] // 40, b[0] % 40]
    n = 0
    for x in b[1:]:
        n = (n << 7) | (x & 0x7F)
        if not x & 0x80:
            p.append(n)
            n = 0
    return ".".join(map(str, p))


def snmp_resposta(dados):
    """Resposta SNMP -> (oid, valor). Valor: int, bytes ou None (fim da tabela/sem objeto). (função pura)"""
    _, msg, _ = _ler_tlv(dados, 0)
    i = 0
    for _ in range(2):                                  # versão, comunidade
        _, _, i = _ler_tlv(msg, i)
    _, pdu, _ = _ler_tlv(msg, i)
    j = 0
    for _ in range(3):                                  # request-id, error-status, error-index
        _, _, j = _ler_tlv(pdu, j)
    _, vbs, _ = _ler_tlv(pdu, j)
    _, vb, _ = _ler_tlv(vbs, 0)
    _, oid, k = _ler_tlv(vb, 0)
    tag, valor, _ = _ler_tlv(vb, k)
    if tag in (0x02, 0x41, 0x42, 0x43):
        return _oid_texto(oid), int.from_bytes(valor, "big", signed=tag == 0x02)
    if tag == 0x04:
        return _oid_texto(oid), valor
    return _oid_texto(oid), None


def _snmp(ip, oid, proximo=False, tempo=1.0):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(tempo)
        s.sendto(snmp_pedido(oid, proximo), (ip, 161))
        return snmp_resposta(s.recv(4096))


def _coluna(ip, base, maximo=12):
    valores, oid = [], base
    for _ in range(maximo):
        oid, v = _snmp(ip, oid, proximo=True)
        if not oid.startswith(base + ".") or v is None:
            break
        valores.append(v)
    return valores


def erros_impressora(bits):
    """Bits do hrPrinterDetectedErrorState -> nomes (função pura)."""
    saida = []
    for i, nome in enumerate(ERROS_IMPRESSORA):
        byte, bit = divmod(i, 8)
        if byte < len(bits) and bits[byte] & (0x80 >> bit):
            saida.append(nome)
    return saida


def nivel_pct(nivel, maximo):
    """Nível do suprimento em % (ou texto quando a impressora não informa o número)."""
    if maximo and maximo > 0 and nivel is not None and nivel >= 0:
        return f"{round(100 * nivel / maximo)}%"
    return {-3: "tem (sem medida)", -2: "desconhecido"}.get(nivel, "desconhecido")


def ler_impressora(ip):
    """{modelo, situacao, erros, suprimentos:[(nome, nível)]} ou {erro}. Leva ~1 s; só quando pedido."""
    try:
        _, desc = _snmp(ip, OID_DESCRICAO)
    except OSError:
        return {"erro": "não respondeu ao SNMP (desligada, SNMP desativado ou comunidade diferente de 'public')"}
    try:
        _, st = _snmp(ip, OID_STATUS)
        _, bits = _snmp(ip, OID_ERROS)
    except OSError:
        st, bits = None, b""
    nomes = _coluna(ip, OID_SUPRIMENTO_NOME)
    maximos = _coluna(ip, OID_SUPRIMENTO_MAX)
    niveis = _coluna(ip, OID_SUPRIMENTO_NIVEL)
    sup = [(n.decode(errors="replace").strip() if isinstance(n, bytes) else str(n),
            nivel_pct(niveis[i] if i < len(niveis) else None, maximos[i] if i < len(maximos) else None))
           for i, n in enumerate(nomes)]
    return {"modelo": desc.decode(errors="replace").strip()[:80] if isinstance(desc, bytes) else None,
            "situacao": {3: "parada (pronta)", 4: "imprimindo", 5: "aquecendo"}.get(st, "desconhecida"),
            "erros": erros_impressora(bits if isinstance(bits, bytes) else b""), "suprimentos": sup}


def texto_impressoras():
    """Para a IA (leitura): toner e erros de todas as impressoras do inventário que estão ligadas."""
    gw = gateway()
    impressoras = [a for a in carregar().values() if tipo_aparelho(a, gw) == "impressora" and online(a)]
    if not impressoras:
        return "Nenhuma impressora ligada no inventário."
    linhas = []
    for a in impressoras:
        r = ler_impressora(a["ip"])
        if "erro" in r:
            linhas.append(f"{nome_exibicao(a)} ({a['ip']}): {r['erro']}")
            continue
        sup = ", ".join(f"{n}: {v}" for n, v in r["suprimentos"][:6]) or "sem dados de toner"
        linhas.append(f"{nome_exibicao(a)} ({a['ip']}): {r['situacao']}; {sup}"
                      + (f"; ALERTA: {', '.join(r['erros'])}" if r["erros"] else ""))
    return "\n".join(linhas)
