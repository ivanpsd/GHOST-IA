"""
GHOST - Vigia da rede (SOMENTE LEITURA): aparelhos críticos e histórico da internet.

- A cada CICLO_S segundos testa o roteador, a internet (8.8.8.8 e 1.1.1.1) e cada aparelho marcado como crítico
  no inventário (servidor, impressoras, câmeras...). Ping; se o aparelho bloqueia ping, tenta portas comuns: uma
  porta que RECUSA a conexão também prova que ele está ligado.
- Fora do ar por FALHAS_PARA_ALERTA testes seguidos: avisa. Quando volta: avisa com quanto tempo ficou fora.
- Grava tudo em dados/internet.jsonl (1 linha por ciclo) e dados/rede_eventos.jsonl (quedas e voltas).
  Guarda RETENCAO_DIAS dias. Serve de prova para cobrar o provedor de internet.
"""
import os
import re
import socket
import threading
import time
from datetime import datetime

from ghost.nucleo import arquivo, caminhos

ARQ_INTERNET = caminhos.dado("internet.jsonl")
ARQ_EVENTOS = caminhos.dado("rede_eventos.jsonl")
CICLO_S = 60
FALHAS_PARA_ALERTA = 2        # 2 minutos fora do ar
RETENCAO_DIAS = 90
ALVOS_INTERNET = ("8.8.8.8", "1.1.1.1")
PORTAS = (445, 80, 443, 9100, 554, 3389, 22, 8080)
SEM_JANELA = 0x08000000
AVISO_SEM_INTERNET = "Senhor, estou sem internet no momento."   # igual a app.AVISO_SEM_INTERNET (cache de voz)

_estado = {}                  # chave -> {"falhas", "fora_desde", "avisado"}
_trava = threading.Lock()


# =============================================================
# 1. TESTES
# =============================================================
def _ping_ms(ip, tempo_ms=1000):
    """Latência em ms (int) ou None."""
    import subprocess
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


def ligado(ip):
    if _ping_ms(ip) is not None:
        return True
    return any(_porta_responde(ip, p) for p in PORTAS)


def gateway():
    import subprocess
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "(Get-NetIPConfiguration | Where-Object {$_.IPv4DefaultGateway} | Select-Object -First 1)"
                            ".IPv4DefaultGateway.NextHop"], capture_output=True, timeout=15,
                           creationflags=SEM_JANELA if os.name == "nt" else 0)
        return r.stdout.decode(errors="replace").strip() or None
    except Exception:
        return None


# =============================================================
# 2. TRANSIÇÕES (função pura: decide quando avisar)
# =============================================================
def registrar_teste(chave, ok, agora, estado=None):
    """Atualiza o estado de um alvo. Devolve ('caiu', None) | ('voltou', minutos_fora) | (None, None)."""
    estado = _estado if estado is None else estado
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
# 3. RESUMO DO HISTÓRICO (função pura)
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
# 4. LAÇO
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


def ciclo(falar=None, gw=None):
    """Um teste completo. Devolve o registro da internet."""
    from ghost.servicos import rede
    agora = time.time()
    gw_ms = _ping_ms(gw) if gw else None
    net = [_ping_ms(ip) for ip in ALVOS_INTERNET]
    net_ok = [x for x in net if x is not None]
    reg = {"t": round(agora), "gw_ms": gw_ms, "net_ms": min(net_ok) if net_ok else None}
    arquivo.acrescentar_jsonl(ARQ_INTERNET, reg)

    alvos = [("internet", "A internet", reg["net_ms"] is not None)]
    if gw:
        alvos.append(("roteador", "O roteador", gw_ms is not None))
    for a in rede.carregar().values():
        if a.get("critico") and a.get("ip"):
            alvos.append((a["mac"], rede.nome_exibicao(a), ligado(a["ip"])))
    for chave, nome, ok in alvos:
        with _trava:
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


def iniciar(falar=None, ocupado=None):
    def laco():
        gw, podado = gateway(), 0.0
        while True:
            try:
                ciclo(falar, gw)
                if time.time() - podado > 86400:
                    _podar(ARQ_INTERNET, RETENCAO_DIAS)
                    _podar(ARQ_EVENTOS, 365)
                    podado = time.time()
                    gw = gateway() or gw
            except Exception as e:
                print(f"\n[REDE]: vigia falhou ({e!r}).")
            time.sleep(CICLO_S)
    threading.Thread(target=laco, daemon=True, name="vigia-rede").start()
