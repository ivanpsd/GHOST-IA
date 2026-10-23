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
import json
import os
import re
import threading
import time
import unicodedata

from ghost.nucleo import arquivo, caminhos

ARQUIVO = caminhos.dado("pessoas.json")
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
        return arquivo.ler_json(ARQUIVO, []) or []
    except arquivo.ArquivoCorrompido:
        return []


def _carregar_para_gravar():
    return arquivo.ler_json(ARQUIVO, []) or []      # corrompido: levanta e não grava por cima


def _gravar(fichas):
    arquivo.salvar_json(ARQUIVO, fichas)


def buscar(nome, exato=False):
    """Ficha pelo nome ou apelido. Sem `exato`, aceita só o primeiro nome se houver UMA ficha com ele
    ("Deborah" acha "Deborah Souza"; "Gustavo Lima" NÃO acha "Gustavo Silva")."""
    alvo = normalizar(nome)
    fichas = carregar()
    for p in fichas:
        if normalizar(p["nome"]) == alvo or alvo in [normalizar(a) for a in p.get("apelidos", [])]:
            return p
    if exato or not alvo or len(alvo.split()) > 1:
        return None
    mesmos = [p for p in fichas if normalizar(p["nome"]).split()[:1] == [alvo]]
    return mesmos[0] if len(mesmos) == 1 else None


def resolver_contato(texto):
    """'minha líder' -> 'Deborah' (pela função ou apelido da ficha). Senão devolve o próprio texto.
    Só troca se UMA ficha corresponder exatamente (função inteira, nome ou apelido): mandar mensagem
    para a pessoa errada é pior do que pesquisar o nome como foi dito."""
    def sem_artigo(t):
        return re.sub(r"^(?:(?:meu|minha|o|a|do|da)\s+)+", "", normalizar(t))

    alvo = sem_artigo(texto)
    if not alvo:
        return texto
    achadas = [p for p in carregar()
               if alvo in [sem_artigo(p.get("nome", "")), sem_artigo(p.get("funcao", ""))]
               + [sem_artigo(a) for a in p.get("apelidos", [])]]
    return achadas[0]["nome"] if len(achadas) == 1 else texto


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
        fichas = _carregar_para_gravar()
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
    alvo = buscar(nome, exato=True) or buscar(nome)
    if not alvo:
        return False
    with _trava:
        _gravar([p for p in _carregar_para_gravar() if p["nome"] != alvo["nome"]])
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
            fichas = _carregar_para_gravar()
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
