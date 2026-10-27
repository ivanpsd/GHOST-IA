"""
GHOST - Máquinas com agente MeshCentral (SOMENTE LEITURA).

Usa a conta "ghost" do MeshCentral (só visualização, sem controle remoto) pelo meshctrl.js, com os dados do .env:
  MESH_URL=wss://ti-ivan:4430   MESH_USUARIO=ghost   MESH_SENHA=...
  MESH_CTRL (opcional) = caminho do meshctrl.js (padrão C:\\MeshCentral\\node_modules\\meshcentral\\meshctrl.js)

Responde: quem está logado, se a máquina está ligada, desde quando, sistema, antivírus, firewall, atualizações e
reinício pendente. Tempo de inatividade da pessoa NÃO é informado (é monitoramento de funcionário; ver plano/LGPD).
Nunca manda comandos às máquinas.
"""
import json
import os
import subprocess
import time
from datetime import datetime

MESHCTRL_PADRAO = r"C:\MeshCentral\node_modules\meshcentral\meshctrl.js"
CACHE_S = 30
SEM_JANELA = 0x08000000

_cache = {"t": 0.0, "dados": None, "erro": None, "t_erro": 0.0}
ESPERA_APOS_ERRO_S = 60       # MeshCentral fora do ar: não tenta de novo a cada pedido (cada tentativa leva ~10 s)


class SemMesh(Exception):
    """MeshCentral não configurado ou fora do ar (mensagem pronta para o usuário)."""


# =============================================================
# 1. LEITURA
# =============================================================
def configurado():
    return all(os.getenv(k) for k in ("MESH_URL", "MESH_USUARIO", "MESH_SENHA"))


def listar(forcar=False):
    """Lista crua de dispositivos (dicts do MeshCentral). Cache de CACHE_S segundos."""
    if not forcar and _cache["dados"] is not None and time.time() - _cache["t"] < CACHE_S:
        return _cache["dados"]
    if not forcar and _cache["erro"] and time.time() - _cache["t_erro"] < ESPERA_APOS_ERRO_S:
        raise SemMesh(_cache["erro"])
    try:
        return _ler()
    except SemMesh as e:
        _cache.update(erro=str(e), t_erro=time.time())
        raise


def _ler():
    if not configurado():
        raise SemMesh("o MeshCentral não está configurado no .env (MESH_URL, MESH_USUARIO, MESH_SENHA)")
    ctrl = os.getenv("MESH_CTRL") or MESHCTRL_PADRAO
    if not os.path.exists(ctrl):
        raise SemMesh(f"não achei o meshctrl.js em {ctrl}")
    cmd = ["node", ctrl, "ListDevices", "--json", "--url", os.environ["MESH_URL"],
           "--loginuser", os.environ["MESH_USUARIO"], "--loginpass", os.environ["MESH_SENHA"]]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=40,
                           creationflags=SEM_JANELA if os.name == "nt" else 0)
    except subprocess.TimeoutExpired as e:
        raise SemMesh("o MeshCentral não respondeu (a janela dele está aberta?)") from e
    try:
        dados = json.loads(r.stdout)
    except ValueError as e:
        msg = (r.stdout + r.stderr).replace(os.environ["MESH_SENHA"], "***").strip().splitlines()
        raise SemMesh("o MeshCentral recusou ou está fora do ar" + (f" ({msg[-1][:120]})" if msg else "")) from e
    _cache.update(t=time.time(), dados=dados, erro=None)
    return dados


# =============================================================
# 2. RESUMO (função pura)
# =============================================================
def resumo(d):
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
    }


def problemas(r):
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


def _apelido(r, inventario):
    """Junta o apelido/responsável do inventário da rede (pelo IP)."""
    a = next((x for x in inventario.values() if x.get("ip") == r["ip"]), None)
    if not a:
        return r["nome"]
    extra = ", ".join(x for x in (a.get("responsavel"), a.get("departamento")) if x)
    return f"{a.get('apelido') or r['nome']}" + (f" ({extra})" if extra else "")


def texto(lista, inventario, acao="listar", termo=""):
    rs = [resumo(d) for d in lista]
    if acao == "procurar":
        t = (termo or "").lower()
        rs = [r for r in rs if t in (r["nome"] or "").lower() or t in (r["ip"] or "") or t in " ".join(r["usuarios"]).lower()
              or t in _apelido(r, inventario).lower()]
        if not rs:
            return f"Nenhuma máquina com agente corresponde a '{termo}'."
    if acao == "alertas":
        com = [(r, problemas(r)) for r in rs]
        com = [(r, p) for r, p in com if p] + [(r, ["desligada"]) for r in rs if not r["ligado"]]
        if not com:
            return f"Nenhum alerta nas {len(rs)} máquinas com agente: antivírus, firewall e atualizações em ordem."
        return "\n".join(f"{_apelido(r, inventario)}: {', '.join(p)}" for r, p in com)
    linhas = []
    for r in rs:
        if not r["ligado"]:
            linhas.append(f"{_apelido(r, inventario)} ({r['ip']}): desligada ou sem agente conectado")
            continue
        desde = f", ligada desde {r['ligado_desde']:%d/%m %H:%M}" if r["ligado_desde"] else ""
        quem = f", logado: {', '.join(r['usuarios'])}" if r["usuarios"] else ", ninguém logado"
        p = problemas(r)
        linhas.append(f"{_apelido(r, inventario)} ({r['ip']}){quem}{desde}; {r['sistema']}; antivírus: {r['antivirus']}"
                      + (f"; ATENÇÃO: {', '.join(p)}" if p else "; segurança em ordem"))
    return f"{len(rs)} máquina(s) com agente:\n" + "\n".join(linhas)


def consultar(acao="listar", termo=""):
    from ghost.servicos import rede
    try:
        lista = listar()
    except SemMesh as e:
        return f"Não consegui consultar as máquinas: {e}."
    return texto(lista, rede.carregar(), acao, termo)
