"""
GHOST - Rede da empresa, SOMENTE LEITURA.

O que faz: descobre os aparelhos da rede local (ping + tabela ARP + nome NetBIOS/DNS), guarda um inventário
(dados/rede.json: MAC, IP, nome na rede, apelido, responsável, departamento, primeira e última vez visto) e
responde "quais máquinas estão ligadas", "a máquina do Gustavo está online?", "o que apareceu de novo",
"como está a internet". Uma varredura em segundo plano a cada INTERVALO_MIN avisa aparelho NOVO na rede.

O que NÃO faz: nada que altere outra máquina (sem desligar, reiniciar, instalar ou mexer em usuários).
Nomear uma máquina ("a 192.168.50.7 é do Gustavo, do TI") muda só o inventário do Ghost.
"""
import ipaddress
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
    return a.get("apelido") or a.get("nome") or a.get("ip") or a.get("mac")


def procurar(inventario, termo):
    """Aparelhos cujo apelido, responsável, departamento, nome na rede, IP ou MAC contém o termo."""
    t = normalizar(termo)
    if not t:
        return []
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


def nomear(alvo, apelido=None, responsavel=None, departamento=None):
    """Dá apelido/responsável/departamento a um aparelho (procurado por IP, MAC ou nome). Só muda o inventário."""
    with _trava:
        inv = carregar()
        achados = procurar(inv, alvo)
        if len(achados) != 1:
            return None, len(achados)
        a = inv[achados[0]["mac"]]
        for campo, valor in (("apelido", apelido), ("responsavel", responsavel), ("departamento", departamento)):
            if valor:
                a[campo] = valor.strip()
        _salvar(inv)
        return a, 1


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
    prefixo = 24
    texto = _rodar(["powershell", "-NoProfile", "-Command",
                    f"(Get-NetIPAddress -IPAddress {ip} -ErrorAction SilentlyContinue).PrefixLength"], 15).strip()
    if texto.isdigit():
        prefixo = max(int(texto), 22)          # rede maior que /22: varre só a parte do próprio IP (até 1024)
    return ip, ipaddress.ip_network(f"{ip}/{prefixo}", strict=False)


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
    extra = ", ".join(x for x in (a.get("responsavel"), a.get("departamento")) if x)
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
    gw = _rodar(["powershell", "-NoProfile", "-Command",
                 "(Get-NetIPConfiguration | Where-Object {$_.IPv4DefaultGateway} | Select-Object -First 1)"
                 ".IPv4DefaultGateway.NextHop"], 15).strip()
    partes = []
    for nome, ip in (("roteador", gw), ("Google DNS", "8.8.8.8"), ("Cloudflare", "1.1.1.1")):
        if not ip:
            continue
        ms, ok = medir(ip)
        partes.append(f"{nome} ({ip}): " + (f"{ms} ms, {ok}/3 respostas" if ms is not None else "sem resposta"))
    return "; ".join(partes)


# =============================================================
# 5. VARREDURA AUTOMÁTICA
# =============================================================
def iniciar(falar=None, ocupado=None):
    def laco():
        primeira = not carregar()            # 1ª vez: só aprende a rede, sem avisar 30 "novos"
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
                print(f"\n[REDE]: varredura falhou ({e!r}).")
            time.sleep(INTERVALO_MIN * 60)
    threading.Thread(target=laco, daemon=True, name="rede").start()
