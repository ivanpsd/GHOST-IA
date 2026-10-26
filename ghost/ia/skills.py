"""
GHOST - Skills ensinadas por voz.

"Ghost, aprenda uma skill: quando eu disser 'começar o dia', abra o Protheus,
espere 5 segundos, abra a planilha de produção e mande bom dia para a Deborah."

A IA converte a descrição em passos usando SOMENTE as ferramentas que já
existem (abrir app/site, pesquisar, digitar, teclas, comandos do Ghost).
O Ghost lê o resumo e só salva depois do seu "sim".
Nenhum código novo é criado ou executado.
Arquivo: dados/skills.json (fica fora do Git).
"""
import json
import os
import re
import threading
import time
import unicodedata
import uuid

from ghost.nucleo import arquivo, caminhos

ARQUIVO = caminhos.dado("skills.json")
MODELO = "openai/gpt-oss-120b"
ESPERA_MAXIMA = 30   # segundos máximos de um passo "esperar"

# Ferramentas permitidas dentro de uma skill (consultas de sistema ficam de fora: precisam de resposta da IA)
PERMITIDAS = {"abrir_aplicativo", "fechar_aplicativo", "abrir_site", "pesquisar_web",
              "digitar_texto", "pressionar_teclas", "comando_ghost", "esperar"}

_trava = threading.Lock()
_cliente = None
_rodando = set()          # skills em execução (uma skill não pode disparar a si mesma em loop)
_trava_rodando = threading.Lock()


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
    """Para alterar: se o arquivo existir mas estiver corrompido, NÃO grava por cima."""
    return arquivo.ler_json(ARQUIVO, []) or []


def _gravar(skills):
    arquivo.salvar_json(ARQUIVO, skills)


def salvar(skill):
    with _trava:
        skills = [s for s in _carregar_para_gravar() if normalizar(s["nome"]) != normalizar(skill["nome"])]
        skills.append(skill)
        _gravar(skills)


def excluir(nome_falado):
    """Apaga a skill com esse nome. Retorna 1, 0 (não achou) ou a lista de nomes se houver várias parecidas
    (nesse caso não apaga nada: antes, "apague a skill relatório" apagava TODAS que tinham "relatório")."""
    alvo = normalizar(nome_falado)
    with _trava:
        skills = _carregar_para_gravar()
        exatas = [s for s in skills if normalizar(s["nome"]) == alvo]
        candidatas = exatas or [s for s in skills if alvo and alvo in normalizar(s["nome"])]
        if len(candidatas) > 1:
            return [s["nome"] for s in candidatas]
        if not candidatas:
            return 0
        _gravar([s for s in skills if s is not candidatas[0]])
    return 1


def encontrar(texto_normalizado):
    """Skill cujo gatilho é a frase dita. Gatilho dentro de uma frase maior só vale se tiver 3+ palavras
    (um gatilho curto como "relatório" sequestrava qualquer pergunta que tivesse essa palavra)."""
    t = re.sub(r"^(?:ghost\s+)", "", texto_normalizado)
    for s in carregar():
        for g in s.get("gatilhos", []):
            g = normalizar(g)
            if not g:
                continue
            if t == g or (len(g.split()) >= 3 and re.search(rf"\b{re.escape(g)}\b", t)):
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
  "aumentar volume", "tirar print")
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
    if any(re.search(r"\b(senha|password|pin)\b", json.dumps(p, ensure_ascii=False).lower()) for p in passos) or \
            re.search(r"\b(senha|password)\b", descricao.lower()):
        raise ValueError("skills não podem guardar senha. Para telas com login, grave a skill pela tela: "
                         "na hora da senha eu peço para o senhor digitar")
    if not passos or not s.get("gatilhos"):
        raise ValueError("não consegui montar passos válidos para essa skill")
    return {"id": "s_" + uuid.uuid4().hex[:8], "nome": s.get("nome", "skill"),
            "gatilhos": s["gatilhos"][:3], "resumo": s.get("resumo", ""), "passos": passos,
            "nao_suportado": s.get("nao_suportado", []), "criada": time.strftime("%Y-%m-%d %H:%M")}


def _segundos(valor, padrao=2.0):
    m = re.search(r"\d+(?:[.,]\d+)?", str(valor))
    return max(0.0, min(float(m.group(0).replace(",", ".")) if m else padrao, ESPERA_MAXIMA))


def executar(skill, falar, pedir_confirmacao):
    if skill.get("tipo") == "demonstracao":            # gravada na tela: repete os cliques/digitação
        from ghost.automacao import automacoes, demonstracao
        return demonstracao.executar(skill, falar, lambda q: automacoes.perguntar(q, falar))
    from ghost.ia import ferramentas
    sid = skill.get("id") or skill.get("nome")
    with _trava_rodando:
        if sid in _rodando:
            print(f"\n[SKILL]: {skill['nome']} já está rodando; chamada repetida ignorada (evita loop).")
            return
        _rodando.add(sid)
    try:
        print(f"\n[SKILL]: {skill['nome']} ({len(skill['passos'])} passos)")
        for i, p in enumerate(skill["passos"], 1):
            nome, args = p.get("ferramenta"), p.get("args", {}) or {}
            print(f"  {i}. {nome} {args}")
            try:
                if nome == "esperar":
                    time.sleep(_segundos(args.get("segundos", 2)))
                elif nome in PERMITIDAS:
                    # não narra cada passo, mas fala perguntas ("quis dizer X?") e avisos de falha
                    ferramentas.executar(nome, args,
                                         lambda t: falar(t) if ("?" in t or "não" in t.lower() or "falha" in t.lower())
                                         else None, pedir_confirmacao)
                    time.sleep(0.5)
            except Exception as e:
                print(f"\n[SKILL]: passo {i} falhou: {e!r}")
                falar(f"Senhor, o passo {i} da skill {skill['nome']} falhou. Parei aqui.")
                return
        falar(f"Skill {skill['nome']} concluída, senhor.")
    finally:
        with _trava_rodando:
            _rodando.discard(sid)
