"""
GHOST - Skills ensinadas por voz.

"Ghost, aprenda uma skill: quando eu disser 'começar o dia', abra o Protheus,
espere 5 segundos, abra a planilha de produção e mande bom dia para a Deborah."

A IA converte a descrição em passos usando SOMENTE as ferramentas que já
existem (abrir app/site, pesquisar, digitar, teclas, comandos do Ghost,
macros). O Ghost lê o resumo e só salva depois do seu "sim".
Nenhum código novo é criado ou executado.
Arquivo: skills.json (fica fora do Git).
"""
import os
import re
import json
import time
import uuid
import threading
import unicodedata

PASTA_GHOST = os.path.dirname(os.path.abspath(__file__))
ARQUIVO = os.path.join(PASTA_GHOST, "skills.json")
MODELO = "openai/gpt-oss-120b"
ESPERA_MAXIMA = 30   # segundos máximos de um passo "esperar"

# Ferramentas permitidas dentro de uma skill (consultas de sistema ficam de fora: precisam de resposta da IA)
PERMITIDAS = {"abrir_aplicativo", "fechar_aplicativo", "abrir_site", "pesquisar_web",
              "digitar_texto", "pressionar_teclas", "comando_ghost", "esperar"}

_trava = threading.Lock()
_cliente = None


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


def _gravar(skills):
    tmp = ARQUIVO + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(skills, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ARQUIVO)


def salvar(skill):
    with _trava:
        skills = [s for s in carregar() if normalizar(s["nome"]) != normalizar(skill["nome"])]
        skills.append(skill)
        _gravar(skills)


def excluir(nome_falado):
    alvo = normalizar(nome_falado)
    with _trava:
        skills = carregar()
        restantes = [s for s in skills if alvo not in normalizar(s["nome"])]
        _gravar(restantes)
    return len(skills) - len(restantes)


def encontrar(texto_normalizado):
    """Skill cujo gatilho é exatamente a frase dita (ou está contido nela)."""
    for s in carregar():
        for g in s.get("gatilhos", []):
            g = normalizar(g)
            if g and (texto_normalizado == g or re.search(rf"\b{re.escape(g)}\b", texto_normalizado)):
                return s
    return None


PROMPT = """Converta a descrição abaixo em uma SKILL para um assistente de voz no Windows.
Use SOMENTE estas ferramentas (passos executados em ordem):
- abrir_aplicativo {{"nome": "..."}}
- fechar_aplicativo {{"nome": "..."}}
- abrir_site {{"url": "..."}}
- pesquisar_web {{"termo": "...", "site": "google"|"youtube"}}
- digitar_texto {{"texto": "..."}}
- pressionar_teclas {{"combo": "ctrl+c"}}
- comando_ghost {{"frase": "..."}}  (frase como o usuário falaria: "mande mensagem para X dizendo Y",
  "aumentar volume", "executar ação <nome de macro cadastrada>", "ativar gestos")
- esperar {{"segundos": N}}  (use entre abrir um programa e interagir com ele, 3 a 8 segundos)

Se algo pedido NÃO puder ser feito com essas ferramentas, liste em "nao_suportado".
NUNCA invente endereços, nomes de arquivo, contatos ou valores que o usuário não disse: se faltar algo
necessário, NÃO crie o passo e escreva em "nao_suportado" como "falta informar: ...".
Gatilhos: 1 a 3 frases curtas que o usuário vai falar para disparar a skill.

Responda SOMENTE JSON:
{{"nome": "...", "gatilhos": ["..."], "resumo": "uma frase em português do que a skill faz",
  "passos": [{{"ferramenta": "...", "args": {{...}}}}], "nao_suportado": ["..."]}}

DESCRIÇÃO DO USUÁRIO: {descricao}"""


def criar_por_descricao(descricao):
    """Retorna um rascunho de skill (ainda não salvo) ou levanta erro."""
    r = _groq().chat.completions.create(
        model=MODELO, messages=[{"role": "user", "content": PROMPT.format(descricao=descricao)}],
        temperature=0, max_tokens=1500, reasoning_effort="medium", response_format={"type": "json_object"})
    s = json.loads(r.choices[0].message.content)
    passos = [p for p in s.get("passos", []) if p.get("ferramenta") in PERMITIDAS]
    if not passos or not s.get("gatilhos"):
        raise ValueError("não consegui montar passos válidos para essa skill")
    return {"id": "s_" + uuid.uuid4().hex[:8], "nome": s.get("nome", "skill"),
            "gatilhos": s["gatilhos"][:3], "resumo": s.get("resumo", ""), "passos": passos,
            "nao_suportado": s.get("nao_suportado", []), "criada": time.strftime("%Y-%m-%d %H:%M")}


def executar(skill, falar, pedir_confirmacao):
    import ferramentas
    print(f"\n[SKILL]: {skill['nome']} ({len(skill['passos'])} passos)")
    for i, p in enumerate(skill["passos"], 1):
        nome, args = p.get("ferramenta"), p.get("args", {}) or {}
        print(f"  {i}. {nome} {args}")
        if nome == "esperar":
            time.sleep(min(float(args.get("segundos", 2)), ESPERA_MAXIMA))
        elif nome in PERMITIDAS:
            # não narra cada passo, mas fala perguntas ("quis dizer X?") e avisos de falha
            ferramentas.executar(nome, args,
                                 lambda t: falar(t) if ("?" in t or "não" in t.lower() or "falha" in t.lower()) else None,
                                 pedir_confirmacao)
            time.sleep(0.5)
    falar(f"Skill {skill['nome']} concluída, senhor.")
