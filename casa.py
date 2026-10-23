"""
GHOST - Casa e escritório inteligentes (pronto para quando houver aparelhos).

Conectores (use um ou os dois; as chaves ficam no .env):
  Home Assistant  -> HA_URL=http://192.168.0.10:8123   HA_TOKEN=<token de longa duração>
  Tuya/Smart Life -> TUYA_API_KEY=...  TUYA_API_SECRET=...  TUYA_REGION=us
Depois diga "Ghost, conectar casa inteligente": ele descobre os aparelhos e
salva a lista em casa_dispositivos.json (fora do Git). Aí:
  "liga a luz da sala", "desliga o ar do escritório", "luz do quarto em 30%",
  "quais aparelhos você controla?", "o ventilador está ligado?"
"""
import os
import re
import json
import arquivo
import difflib
import unicodedata

import requests

PASTA_GHOST = os.path.dirname(os.path.abspath(__file__))
ARQUIVO = os.path.join(PASTA_GHOST, "casa_dispositivos.json")
DOMINIOS_HA = ("light", "switch", "fan", "climate", "cover", "media_player", "input_boolean")
TIPOS = {"light": "luz", "switch": "tomada/interruptor", "fan": "ventilador", "climate": "ar-condicionado",
         "cover": "cortina/portão", "media_player": "TV/som", "input_boolean": "chave"}

INSTRUCOES = """Para conectar a casa inteligente, coloque no arquivo .env do Ghost UMA destas opções:

1) Home Assistant (recomendado, conversa com quase todas as marcas):
   HA_URL=http://IP-DO-HOME-ASSISTANT:8123
   HA_TOKEN=token criado em: Perfil > Segurança > Tokens de acesso de longa duração

2) Tuya / Smart Life (lâmpadas e tomadas Wi-Fi comuns):
   Crie um projeto Cloud em iot.tuya.com, vincule o app Smart Life e copie:
   TUYA_API_KEY=...   TUYA_API_SECRET=...   TUYA_REGION=us

Depois reinicie o Ghost e diga: "Ghost, conectar casa inteligente"."""


def normalizar(t):
    t = unicodedata.normalize("NFD", (t or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", t)).strip()


def conectores():
    c = []
    if os.getenv("HA_URL") and os.getenv("HA_TOKEN"):
        c.append("homeassistant")
    if os.getenv("TUYA_API_KEY") and os.getenv("TUYA_API_SECRET"):
        c.append("tuya")
    return c


def carregar():
    try:
        with open(ARQUIVO, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def configurado():
    return bool(carregar())


# ---------------- Home Assistant ----------------
def _ha(metodo, caminho, dados=None):
    r = requests.request(metodo, os.getenv("HA_URL").rstrip("/") + caminho, json=dados, timeout=8,
                         headers={"Authorization": f"Bearer {os.getenv('HA_TOKEN')}"})
    r.raise_for_status()
    return r.json() if r.content else {}


def _descobrir_ha():
    itens = []
    for e in _ha("GET", "/api/states"):
        dominio = e["entity_id"].split(".")[0]
        if dominio in DOMINIOS_HA:
            itens.append({"id": e["entity_id"], "nome": e["attributes"].get("friendly_name", e["entity_id"]),
                          "tipo": dominio, "conector": "homeassistant"})
    return itens


def _controlar_ha(d, acao, valor):
    servico = {"ligar": "turn_on", "desligar": "turn_off", "alternar": "toggle"}[acao]
    dados = {"entity_id": d["id"]}
    if acao == "ligar" and valor is not None:
        if d["tipo"] == "light":
            dados["brightness_pct"] = max(1, min(100, int(valor)))
        elif d["tipo"] == "climate":
            servico, dados["temperature"] = "set_temperature", float(valor)
    _ha("POST", f"/api/services/{d['tipo']}/{servico}", dados)


def _estado_ha(d):
    e = _ha("GET", f"/api/states/{d['id']}")
    extra = f", {int(float(e['attributes'].get('temperature')))} graus" if d["tipo"] == "climate" and e["attributes"].get("temperature") else ""
    return {"on": "ligado", "off": "desligado", "open": "aberto", "closed": "fechado"}.get(e["state"], e["state"]) + extra


# ---------------- Tuya / Smart Life ----------------
def _tuya():
    import tinytuya
    return tinytuya.Cloud(apiRegion=os.getenv("TUYA_REGION", "us"), apiKey=os.getenv("TUYA_API_KEY"),
                          apiSecret=os.getenv("TUYA_API_SECRET"))


def _descobrir_tuya():
    return [{"id": d["id"], "nome": d.get("name", d["id"]), "tipo": d.get("category", "switch"), "conector": "tuya"}
            for d in (_tuya().getdevices() or [])]


def _codigo_tuya(c, d, prefixos):
    funcs = c.getfunctions(d["id"]).get("result", {}).get("functions", [])
    return next((f["code"] for p in prefixos for f in funcs if f["code"].startswith(p)), None)


def _controlar_tuya(d, acao, valor):
    c = _tuya()
    cod = _codigo_tuya(c, d, ("switch_led", "switch_1", "switch"))
    if not cod:
        raise RuntimeError("aparelho sem comando de liga/desliga")
    if acao == "alternar":
        atual = {s["code"]: s["value"] for s in c.getstatus(d["id"]).get("result", [])}
        ligar = not atual.get(cod, False)
    else:
        ligar = acao == "ligar"
    cmds = [{"code": cod, "value": ligar}]
    if ligar and valor is not None:
        brilho = _codigo_tuya(c, d, ("bright_value",))
        if brilho:
            cmds.append({"code": brilho, "value": int(10 + (1000 - 10) * max(1, min(100, int(valor))) / 100)})
    c.sendcommand(d["id"], {"commands": cmds})


def _estado_tuya(d):
    st = {s["code"]: s["value"] for s in _tuya().getstatus(d["id"]).get("result", [])}
    chave = next((k for k in st if k.startswith("switch")), None)
    return ("ligado" if st.get(chave) else "desligado") if chave else "estado desconhecido"


# ---------------- comum ----------------
def descobrir():
    """Procura os aparelhos em todos os conectores configurados e salva a lista."""
    cons = conectores()
    if not cons:
        print("\n" + INSTRUCOES)
        return "Senhor, ainda não há nenhum conector configurado. Deixei as instruções no terminal e no README."
    achados, erros = [], []
    for c in cons:
        try:
            achados += _descobrir_ha() if c == "homeassistant" else _descobrir_tuya()
        except Exception as e:
            erros.append(f"{c}: {e}")
    if achados:
        arquivo.salvar_json(ARQUIVO, achados)
    msg = f"Encontrei {len(achados)} aparelho{'s' if len(achados) != 1 else ''}, senhor."
    if erros:
        print("\n[CASA]: " + " | ".join(erros))
        msg += " Um dos conectores deu erro; detalhes no terminal."
    return msg


def encontrar(nome):
    alvo = normalizar(nome)
    aparelhos = carregar()
    if not aparelhos or not alvo:
        return None
    pont = [(difflib.SequenceMatcher(None, alvo, normalizar(d["nome"])).ratio()
             + (0.3 if all(p in normalizar(d["nome"]) for p in alvo.split()) else 0), d) for d in aparelhos]
    melhor = max(pont, key=lambda x: x[0])
    return melhor[1] if melhor[0] >= 0.55 else None


def controlar(nome, acao, valor=None):
    if not configurado():
        return "Senhor, ainda não conectei nenhum aparelho. Diga: conectar casa inteligente."
    d = encontrar(nome)
    if not d:
        return f"Senhor, não encontrei o aparelho {nome}."
    try:
        (_controlar_ha if d["conector"] == "homeassistant" else _controlar_tuya)(d, acao, valor)
    except Exception as e:
        return f"Senhor, falhou ao controlar {d['nome']}: {e}."
    feito = {"ligar": "ligou", "desligar": "desligou", "alternar": "trocou de estado"}[acao]
    extra = ""
    if valor is not None and acao == "ligar":
        extra = f" em {int(valor)} graus" if d["tipo"] == "climate" else f" em {int(valor)}%"
    return f"Pronto, senhor: {d['nome']} {feito}{extra}."


def estado(nome):
    d = encontrar(nome)
    if not d:
        return f"Senhor, não encontrei o aparelho {nome}."
    try:
        return f"{d['nome']}: {(_estado_ha if d['conector'] == 'homeassistant' else _estado_tuya)(d)}."
    except Exception as e:
        return f"Senhor, não consegui ler {d['nome']}: {e}."


def listar():
    aparelhos = carregar()
    if not aparelhos:
        return "Ainda não controlo nenhum aparelho, senhor."
    return "Controlo: " + ", ".join(f"{d['nome']} ({TIPOS.get(d['tipo'], d['tipo'])})" for d in aparelhos[:15]) + "."
