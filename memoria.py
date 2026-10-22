"""
GHOST - Memória de aprendizado automático.

Depois de cada conversa com a IA, uma chamada rápida em segundo plano
analisa o que você disse e guarda só fatos duradouros (preferências,
pessoas, trabalho, rotina). Esses fatos entram em todas as perguntas
seguintes, inclusive depois de reiniciar o computador.

Arquivo: memoria_aprendizado.json (fica fora do Git pelo .gitignore: *.json)
"""
import os
import re
import json
import threading
from datetime import date

PASTA_GHOST = os.path.dirname(os.path.abspath(__file__))
ARQUIVO = os.path.join(PASTA_GHOST, "memoria_aprendizado.json")
MODELO_MEMORIA = "openai/gpt-oss-20b"   # modelo rápido e barato só para extrair fatos
MAX_FATOS = 150
MOSTRAR_APRENDIZADO = True             # imprime no terminal/log o que foi aprendido ou esquecido

_trava = threading.Lock()

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


def carregar_fatos():
    try:
        with open(ARQUIVO, "r", encoding="utf-8") as f:
            return json.load(f).get("fatos", [])
    except Exception:
        return []

def _salvar_fatos(fatos):
    temp = ARQUIVO + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump({"fatos": fatos[-MAX_FATOS:]}, f, ensure_ascii=False, indent=2)
    os.replace(temp, ARQUIVO)  # grava inteiro ou nada: não corrompe o arquivo

def texto_para_prompt():
    """Bloco anexado à instrução do sistema em cada pergunta."""
    fatos = carregar_fatos()
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
    try:
        with _trava:
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

            remover = {int(i) for i in dados.get("remover", []) if str(i).isdigit() and int(i) < len(fatos)}
            existentes = {f["texto"].strip().lower() for f in fatos}
            novos = [t.strip() for t in dados.get("adicionar", [])
                     if isinstance(t, str) and t.strip() and t.strip().lower() not in existentes]
            if not remover and not novos:
                return

            if MOSTRAR_APRENDIZADO:
                for i in sorted(remover):
                    print(f"\n[MEMÓRIA]: esqueci -> {fatos[i]['texto']}")
                for t in novos:
                    print(f"\n[MEMÓRIA]: aprendi -> {t}")

            fatos = [f for i, f in enumerate(fatos) if i not in remover]
            hoje = date.today().isoformat()
            fatos += [{"texto": t, "data": hoje} for t in novos]
            _salvar_fatos(fatos)
    except Exception as e:
        print(f"\n[MEMÓRIA]: falha ao aprender ({e})")

def aprender_em_segundo_plano(client_groq, pergunta, resposta):
    """Não atrasa a resposta: roda depois, em outra thread."""
    threading.Thread(target=_aprender, args=(client_groq, pergunta, resposta), daemon=True).start()

def substituir_categoria(prefixo, novos):
    """Troca todos os fatos que começam com `prefixo` pela lista nova (usado pelos padrões de comportamento)."""
    if not novos:
        return
    with _trava:
        fatos = [f for f in carregar_fatos() if not f["texto"].startswith(prefixo)]
        hoje = date.today().isoformat()
        fatos += [{"texto": t.strip(), "data": hoje} for t in novos if t.strip().startswith(prefixo)]
        _salvar_fatos(fatos)
    if MOSTRAR_APRENDIZADO:
        for t in novos:
            print(f"\n[MEMÓRIA]: padrão -> {t}")
