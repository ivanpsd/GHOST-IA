"""
GHOST - Fichas de pessoas (sem biometria).

O Ghost só sabe o que for DITO a ele:
  "Ghost, esta é a Deborah, minha líder, cuida do financeiro."
  "Ghost, anota sobre o Gustavo: telefone 11 99999-0000, cuida do TI."
  "Ghost, o que você sabe sobre a Deborah?"
  "Ghost, esqueça a ficha do Gustavo."
Quem está falando também é por declaração:
  "Aqui é a Deborah"  ->  o Ghost passa a responder a ela, usando a ficha.
  "Aqui é o Ivan"     ->  volta para o dono (ou volta sozinho após alguns minutos parado).
Arquivo: pessoas.json (fora do Git).
"""
import os
import re
import json
import time
import threading
import unicodedata

PASTA_GHOST = os.path.dirname(os.path.abspath(__file__))
ARQUIVO = os.path.join(PASTA_GHOST, "pessoas.json")
DONO = "Ivan"
MODELO = "openai/gpt-oss-20b"
VOLTA_PARA_DONO_MIN = 15   # sem conversa por esse tempo, o falante volta a ser o dono

_trava = threading.Lock()
_cliente = None
_falante = None            # None = dono
_falante_desde = 0.0


def normalizar(t):
    t = unicodedata.normalize("NFD", (t or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", t)).strip()


def _groq():
    global _cliente
    if _cliente is None:
        from groq import Groq
        _cliente = Groq(api_key=os.getenv("GROQ_API_KEY"))
    return _cliente


def carregar():
    try:
        with open(ARQUIVO, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _gravar(fichas):
    tmp = ARQUIVO + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(fichas, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ARQUIVO)


def buscar(nome):
    alvo = normalizar(nome)
    for p in carregar():
        if normalizar(p["nome"]) == alvo or alvo in [normalizar(a) for a in p.get("apelidos", [])]:
            return p
    for p in carregar():  # "Deborah Souza" quando falou só "Deborah"
        if alvo and alvo.split()[0] == normalizar(p["nome"]).split()[0]:
            return p
    return None


def resolver_contato(texto):
    """'minha líder' -> 'Deborah' (pela função ou apelido da ficha). Senão devolve o próprio texto."""
    alvo = normalizar(texto)
    alvo_sem = re.sub(r"^(?:meu|minha|o|a|do|da)\s+", "", alvo)
    for p in carregar():
        campos = [normalizar(p["nome"]), normalizar(p.get("funcao", ""))] + [normalizar(a) for a in p.get("apelidos", [])]
        if alvo_sem and any(alvo_sem == c or (len(alvo_sem) > 3 and alvo_sem in c) for c in campos if c):
            return p["nome"]
    return texto


PROMPT = """Extraia de uma frase em português as informações sobre UMA pessoa que está sendo apresentada
ou descrita a um assistente. Não invente nada que não esteja na frase.
Responda SOMENTE JSON: {{"nome": "...", "funcao": "cargo/relação com o usuário ou vazio",
"telefone": "só dígitos ou vazio", "apelidos": ["..."], "notas": ["fatos curtos sobre a pessoa"]}}
FRASE: {frase}"""


def registrar(frase):
    """Cria ou completa a ficha a partir do que foi dito. Retorna a ficha."""
    r = _groq().chat.completions.create(
        model=MODELO, messages=[{"role": "user", "content": PROMPT.format(frase=frase)}],
        temperature=0, max_tokens=600, reasoning_effort="low", response_format={"type": "json_object"})
    d = json.loads(r.choices[0].message.content)
    nome = (d.get("nome") or "").strip()
    if not nome:
        raise ValueError("não entendi o nome da pessoa")
    with _trava:
        fichas = carregar()
        p = next((x for x in fichas if normalizar(x["nome"]) == normalizar(nome)), None)
        if not p:
            p = {"nome": nome, "funcao": "", "telefone": "", "apelidos": [], "notas": [],
                 "criada": time.strftime("%Y-%m-%d")}
            fichas.append(p)
        for campo in ("funcao", "telefone"):
            if d.get(campo):
                p[campo] = d[campo]
        p["apelidos"] = sorted(set(p["apelidos"]) | {a for a in d.get("apelidos", []) if a})
        p["notas"] += [n for n in d.get("notas", []) if n and n not in p["notas"]]
        p["atualizada"] = time.strftime("%Y-%m-%d %H:%M")
        _gravar(fichas)
    return p


def excluir(nome):
    alvo = buscar(nome)
    if not alvo:
        return False
    with _trava:
        _gravar([p for p in carregar() if p["nome"] != alvo["nome"]])
    return True


def descrever(p):
    partes = [p["nome"]]
    if p.get("funcao"):
        partes.append(p["funcao"])
    if p.get("telefone"):
        partes.append(f"telefone {p['telefone']}")
    partes += p.get("notas", [])[-5:]
    return ". ".join(partes) + "."


# -------------------------------------------------------------
# QUEM ESTÁ FALANDO (por declaração)
# -------------------------------------------------------------
def definir_falante(nome):
    global _falante, _falante_desde
    if normalizar(nome).split()[0] == normalizar(DONO):
        _falante = None
        return None
    p = buscar(nome)
    if not p:
        with _trava:
            fichas = carregar()
            p = {"nome": nome.strip().title(), "funcao": "", "telefone": "", "apelidos": [], "notas": [],
                 "criada": time.strftime("%Y-%m-%d")}
            fichas.append(p)
            _gravar(fichas)
    _falante, _falante_desde = p["nome"], time.time()
    return p


def renovar_falante():
    global _falante_desde
    if _falante:
        _falante_desde = time.time()


def falante_atual():
    """Nome de quem está falando, ou None se for o dono."""
    global _falante
    if _falante and time.time() - _falante_desde > VOLTA_PARA_DONO_MIN * 60:
        _falante = None
    return _falante


def texto_para_prompt():
    fichas = carregar()
    texto = f"\n\nO dono do Ghost (o usuário principal) se chama {DONO}. Nunca use outro nome para ele."
    if fichas:
        linhas = "\n".join(f"- {p['nome']}" + (f" ({p['funcao']})" if p.get("funcao") else "") for p in fichas[:40])
        texto += f"\n\nPESSOAS CONHECIDAS (fichas que o usuário ditou):\n{linhas}"
    f = falante_atual()
    if f:
        p = buscar(f)
        texto += (f"\n\nQUEM ESTÁ FALANDO AGORA não é o dono ({DONO}), é {f}. Trate essa pessoa pelo nome "
                  f"(não por 'senhor'). Ficha: {descrever(p) if p else f}")
    return texto
