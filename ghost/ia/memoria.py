"""
GHOST - Memória de aprendizado automático.

Depois de cada conversa com a IA, uma chamada rápida em segundo plano
analisa o que você disse e guarda só fatos duradouros (preferências,
pessoas, trabalho, rotina). Esses fatos entram em todas as perguntas
seguintes, inclusive depois de reiniciar o computador.

Arquivo: dados/memoria_aprendizado.json (fora do Git).
"""
import json
import re
import threading
from datetime import date

from ghost.nucleo import arquivo, caminhos

ARQUIVO = caminhos.dado("memoria_aprendizado.json")
MODELO_MEMORIA = "openai/gpt-oss-20b"   # modelo rápido e barato só para extrair fatos
MAX_FATOS = 150
MOSTRAR_APRENDIZADO = True             # imprime no terminal/log o que foi aprendido ou esquecido

_trava = threading.RLock()

PROMPT_EXTRACAO = """Você é o módulo de memória de um assistente pessoal.
Analise a fala do USUÁRIO e decida se ela contém fatos DURADOUROS sobre ele que valem ser lembrados no futuro.

Guarde apenas o que o usuário AFIRMOU CLARAMENTE sobre si: preferências, gostos, rotina, trabalho, empresa,
cargo, projetos, pessoas próximas e seus papéis, equipamentos, cidade, objetivos, como quer ser atendido.

NÃO guarde:
- o NOME do usuário (ele se chama Ivan; isso é fixo e não vem da memória) nem nomes que contradigam isso;
- respostas curtas a perguntas do assistente ("não preciso de nada", "estou bem", "sim", "pode");
- frases soltas, sem sentido completo ou que pareçam erro de transcrição (na dúvida, NÃO guarde);
- perguntas, curiosidades gerais, o que o ASSISTENTE disse, fatos passageiros (ex.: "estou com fome");
- endereço completo (rua e número): no máximo cidade e bairro;
- dados sensíveis (senhas, chaves, documentos, números de cartão ou conta, saúde).

Se a fala corrigir ou contradizer um fato já salvo, remova o antigo e adicione o novo.
Se o usuário pedir para esquecer algo, remova o fato correspondente.
Escreva cada fato novo em uma frase curta, em português, na 3ª pessoa (ex.: "O usuário trabalha com PCP.").
Não repita fatos já salvos.

FATOS JÁ SALVOS (número: fato):
{fatos}

USUÁRIO disse: {pergunta}
ASSISTENTE respondeu: {resposta}

Responda SOMENTE com JSON neste formato:
{{"adicionar": ["fato novo", ...], "remover": [números dos fatos a remover]}}
Se não houver nada, responda {{"adicionar": [], "remover": []}}"""


def _carregar_sem_trava():
    dados = arquivo.ler_json(ARQUIVO, {}) or {}
    return list(dados.get("fatos", [])) if isinstance(dados, dict) else []


def carregar_fatos():
    with _trava:
        try:
            return _carregar_sem_trava()
        except arquivo.ArquivoCorrompido:
            return []


def _salvar_fatos(fatos):
    arquivo.salvar_json(ARQUIVO, {"fatos": fatos[-MAX_FATOS:]}, indent=2)


FATOS_NO_PROMPT = 14        # antes ia a lista inteira (~1.100 tokens por pergunta); agora só o que importa


def escolher_fatos(fatos, pergunta, limite=FATOS_NO_PROMPT):
    """Os fatos mais ligados à pergunta (busca por palavras) + os mais recentes para completar (função pura)."""
    if len(fatos) <= limite:
        return fatos
    from collections import Counter

    from ghost.ia import memoria_longa
    notas = memoria_longa.pontuar(pergunta or "", [Counter(memoria_longa.normalizar(f["texto"])) for f in fatos])
    relevantes = [i for i in sorted(range(len(fatos)), key=lambda i: -notas[i]) if notas[i] > 0][:limite - 4]
    for i in range(len(fatos) - 1, -1, -1):                  # completa com os mais novos
        if len(relevantes) >= limite:
            break
        if i not in relevantes:
            relevantes.append(i)
    return [fatos[i] for i in sorted(relevantes)]


def texto_para_prompt(pergunta=""):
    """Bloco anexado à instrução do sistema em cada pergunta."""
    fatos = escolher_fatos(carregar_fatos(), pergunta)
    if not fatos:
        return ""
    linhas = "\n".join(f"- {f['texto']}" for f in fatos)
    return ("\n\nMEMÓRIA DE LONGO PRAZO (fatos que você aprendeu sobre o usuário em conversas anteriores; "
            "use quando forem relevantes, sem citá-los à toa):\n" + linhas)

def _ler_json(texto):
    try:
        return json.loads(texto)
    except Exception:
        m = re.search(r"\{.*\}", texto or "", re.S)
        return json.loads(m.group(0)) if m else {}

def _aprender(client_groq, pergunta, resposta):
    """A chamada à IA (pode levar segundos) acontece SEM a trava; depois relê os fatos e aplica.
    Assim ninguém fica esperando a rede para ler ou gravar a memória."""
    try:
        fatos = carregar_fatos()
        lista = "\n".join(f"{i}: {f['texto']}" for i, f in enumerate(fatos)) or "(nenhum)"
        completion = client_groq.chat.completions.create(
            model=MODELO_MEMORIA,
            messages=[{"role": "user", "content": PROMPT_EXTRACAO.format(
                fatos=lista, pergunta=pergunta, resposta=resposta)}],
            temperature=0,
            max_tokens=800,
            reasoning_effort="low",
            response_format={"type": "json_object"},
        )
        dados = _ler_json(completion.choices[0].message.content)
        if not isinstance(dados, dict):
            return
        # os números se referem à lista que a IA viu: converte em textos (a lista pode ter mudado)
        remover_textos = {fatos[int(i)]["texto"] for i in dados.get("remover", [])
                          if str(i).isdigit() and int(i) < len(fatos)}
        novos = [t.strip() for t in dados.get("adicionar", []) if isinstance(t, str) and t.strip()]
        if not remover_textos and not novos:
            return
        with _trava:
            try:
                atuais = _carregar_sem_trava()
            except arquivo.ArquivoCorrompido:
                return                      # não grava por cima de um arquivo que não conseguiu ler
            existentes = {f["texto"].strip().lower() for f in atuais}
            novos = [t for t in novos if t.lower() not in existentes]
            atuais = [f for f in atuais if f["texto"] not in remover_textos]
            hoje = date.today().isoformat()
            atuais += [{"texto": t, "data": hoje} for t in novos]
            _salvar_fatos(atuais)
        if MOSTRAR_APRENDIZADO:
            for t in sorted(remover_textos):
                print(f"\n[MEMÓRIA]: esqueci -> {t}")
            for t in novos:
                print(f"\n[MEMÓRIA]: aprendi -> {t}")
    except Exception as e:
        print(f"\n[MEMÓRIA]: falha ao aprender ({e})")

def vale_aprender(pergunta):
    """Só gasta uma chamada de IA quando a fala PODE ter um fato sobre o senhor (função pura).
    'Obrigado', 'abre o Excel', 'que horas são' não têm: antes cada um custava ~1.500 tokens da cota."""
    n = (pergunta or "").lower()
    if len(n.split()) < 5:
        return False
    return bool(re.search(r"\b(eu|meu|minha|meus|minhas|me chame|me chama|prefiro|gosto|odeio|trabalho|sou|tenho|"
                          r"moro|nosso|nossa|nossos|nossas|sempre|nunca|lembre|esquec|minha esposa|meu filho)\b", n))


def aprender_em_segundo_plano(client_groq, pergunta, resposta):
    """Não atrasa a resposta: roda depois, em outra thread."""
    if not vale_aprender(pergunta):
        return
    threading.Thread(target=_aprender, args=(client_groq, pergunta, resposta), daemon=True).start()

def substituir_categoria(prefixo, novos):
    """Troca todos os fatos que começam com `prefixo` pela lista nova (usado pelos padrões de comportamento)."""
    if not novos:
        return
    with _trava:
        try:
            fatos = [f for f in _carregar_sem_trava() if not f["texto"].startswith(prefixo)]
        except arquivo.ArquivoCorrompido:
            return
        hoje = date.today().isoformat()
        fatos += [{"texto": t.strip(), "data": hoje} for t in novos if t.strip().startswith(prefixo)]
        _salvar_fatos(fatos)
    if MOSTRAR_APRENDIZADO:
        for t in novos:
            print(f"\n[MEMÓRIA]: padrão -> {t}")
