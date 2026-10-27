"""
GHOST - Telas (HUDs) de visualização, abertas por voz ("mostre o link neural da rede").

Cada HUD = um arquivo painel_web/hud_<nome>.html (desenho e interação) + uma função aqui que monta os dados (JSON).
O servidor do painel serve os dois (só em 127.0.0.1, com a chave da sessão) e abre a tela numa janela própria.
Os HUDs só MOSTRAM: nenhum botão manda comando para máquinas.
"""
import re
import time

HUDS = {
    "rede": "Link neural da rede",
}


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
_gw = {"ip": None, "t": 0.0}


def _gateway():
    """IP do roteador (consulta o Windows no máximo a cada 10 min)."""
    if not _gw["ip"] or time.time() - _gw["t"] > 600:
        from ghost.servicos import monitor_rede
        _gw.update(ip=monitor_rede.gateway() or _gw["ip"], t=time.time())
    return _gw["ip"]


def dados_rede():
    """Tudo o que o mapa da rede desenha: internet, roteador, aparelhos (com grupo, tipo, estado) e agentes."""
    from ghost.nucleo import arquivo
    from ghost.servicos import meshcentral, monitor_rede, rede
    agora = time.time()
    inv = rede.carregar()
    ultima = (arquivo.ler_jsonl(monitor_rede.ARQ_INTERNET) or [{}])[-1]
    gw = _gateway()
    agentes = {}
    try:
        if meshcentral.configurado():
            for d in meshcentral.listar():
                r = meshcentral.resumo(d)
                agentes[r["ip"]] = {"logado": r["usuarios"], "sistema": r["sistema"], "antivirus": r["antivirus"],
                                    "problemas": meshcentral.problemas(r), "ligado_desde": str(r["ligado_desde"] or "")}
    except Exception:
        pass
    quedas = {k for k, e in monitor_rede._estado.items() if e.get("avisado")}
    aparelhos = []
    for mac, a in inv.items():
        tipo = tipo_aparelho(a, gw)
        aparelhos.append({
            "id": mac, "nome": rede.nome_exibicao(a), "nome_rede": a.get("nome"), "apelido": a.get("apelido"),
            "responsavel": a.get("responsavel"), "departamento": a.get("departamento"), "ip": a.get("ip"), "mac": mac,
            "grupo_trabalho": a.get("grupo"), "tipo": tipo,
            "grupo": a.get("departamento") or GRUPO_DO_TIPO.get(tipo, "Outros"),
            "ligado": rede.online(a, agora), "critico": bool(a.get("critico")), "fora_do_ar": mac in quedas,
            "novo": agora - a.get("primeira_vez", 0) < 86400, "primeira_vez": a.get("primeira_vez"),
            "ultima_vez": a.get("ultima_vez"), "agente": agentes.get(a.get("ip")),
        })
    return {"gerado": agora, "gateway": gw,
            "internet": {"ok": ultima.get("net_ms") is not None if ultima else None, "ms": ultima.get("net_ms"),
                         "roteador_ms": ultima.get("gw_ms"), "quando": ultima.get("t"), "fora": "internet" in quedas},
            "aparelhos": aparelhos}


DADOS = {"rede": dados_rede}
