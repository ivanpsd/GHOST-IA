"""
GHOST - Aprende a sua rotina observando QUAL programa/janela está em uso.

- A cada poucos segundos anota o programa em foco e o título da janela
  (ex.: EXCEL.EXE — "Produção Outubro.xlsx"). Nada de captura de tela.
- Tudo fica só no seu PC (dados/rotina_log.jsonl, fora do Git).
- A cada RESUMO_HORAS horas, a IA resume a rotina: os padrões vão para a
  memória de longo prazo ("Rotina: ...") e, se notar uma sequência repetida,
  o Ghost SUGERE criar uma skill. Ele só cria se você disser "sim".
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import threading
import time
from datetime import datetime

from ghost.nucleo import arquivo, caminhos, sistema

ARQUIVO_LOG = caminhos.dado("rotina_log.jsonl")
MAX_BYTES_LOG = 5_000_000   # acima disso o log antigo vira rotina_log.jsonl.1 (guarda ~2 meses)

OBSERVAR_AO_INICIAR = True
INTERVALO = 10              # segundos entre leituras da janela em foco
GUARDAR_TITULOS = True      # False = guarda só o nome do programa (mais privado)
OCIOSO_SEGUNDOS = 300       # sem mexer no PC por mais que isso = ausente
RESUMO_HORAS = 3
MAX_LINHAS_RESUMO = 400
IGNORAR = {"pythonw.exe", "python.exe", "lockapp.exe", "searchhost.exe", "shellexperiencehost.exe"}

user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
observando = False
_geracao = 0
_falar = _ocupado = _cliente = _pedir_confirmacao = None


def _janela_em_foco():
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None, None
    tam = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(tam + 1)
    user32.GetWindowTextW(hwnd, buf, tam + 1)
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    nome = None
    h = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if h:
        caminho = ctypes.create_unicode_buffer(520)
        n = wt.DWORD(520)
        if kernel32.QueryFullProcessImageNameW(h, 0, caminho, ctypes.byref(n)):
            nome = os.path.basename(caminho.value)
        kernel32.CloseHandle(h)
    return nome, buf.value


def _ocioso():
    return sistema.segundos_ocioso() > OCIOSO_SEGUNDOS


def _gravar(evento):
    try:
        if os.path.getsize(ARQUIVO_LOG) > MAX_BYTES_LOG:
            os.replace(ARQUIVO_LOG, ARQUIVO_LOG + ".1")
    except OSError:
        pass
    arquivo.acrescentar_jsonl(ARQUIVO_LOG, evento)


def _eventos():
    """Eventos válidos do log (linhas corrompidas ou incompletas são ignoradas)."""
    return [e for e in arquivo.ler_jsonl(ARQUIVO_LOG)
            if isinstance(e, dict) and isinstance(e.get("inicio"), str) and isinstance(e.get("segundos"), int)
            and isinstance(e.get("app"), str)]


def _loop_observar(geracao):
    atual, inicio = None, time.time()
    ult_resumo = time.time()
    while observando and geracao == _geracao:
        try:
            app, titulo = _janela_em_foco()
            chave = ("ausente", "") if _ocioso() else (app, titulo if GUARDAR_TITULOS else "")
            if chave[0] and chave[0].lower() in IGNORAR:
                chave = atual or chave
            if chave != atual:
                if atual and time.time() - inicio >= INTERVALO:
                    _gravar({"inicio": datetime.fromtimestamp(inicio).isoformat(timespec="seconds"),
                             "segundos": int(time.time() - inicio), "app": atual[0], "janela": atual[1]})
                atual, inicio = chave, time.time()
            if time.time() - ult_resumo > RESUMO_HORAS * 3600:
                ult_resumo = time.time()
                threading.Thread(target=resumir, daemon=True, name="rotina-resumo").start()
        except Exception as e:
            print(f"\n[ROTINA]: erro: {e!r}")
        time.sleep(INTERVALO)


def ativar(ligar=True, falar=None):
    global observando, _geracao
    if ligar and not observando:
        observando = True
        _geracao += 1          # um desliga/liga rápido não deixa dois loops gravando em dobro
        threading.Thread(target=_loop_observar, args=(_geracao,), daemon=True, name="rotina").start()
        if falar:
            falar("Observação da rotina ativada, senhor.")
    elif not ligar and observando:
        observando = False
        if falar:
            falar("Observação da rotina desativada, senhor.")
    elif falar:
        falar("A observação da rotina já está " + ("ativa" if ligar else "desligada") + ", senhor.")


def iniciar(falar, ocupado, cliente, pedir_confirmacao):
    global _falar, _ocupado, _cliente, _pedir_confirmacao
    _falar, _ocupado, _cliente, _pedir_confirmacao = falar, ocupado, cliente, pedir_confirmacao
    if OBSERVAR_AO_INICIAR:
        ativar(True)


PROMPT = """Abaixo está o registro de uso do computador de um usuário (início, segundos, programa, título da janela).
1) Identifique até 6 PADRÕES DE ROTINA com evidência (horários, programas e arquivos mais usados, sequências).
   Cada um em uma frase curta, 3ª pessoa, começando com "Rotina:".
2) Se houver uma SEQUÊNCIA de abrir programas/sites/arquivos que se repete e poderia virar um atalho,
   sugira até 2 skills: nome curto e descrição em linguagem natural dos passos (o que abrir, em que ordem).
Não inclua conteúdo sensível de títulos (valores, nomes de clientes, assuntos de e-mail).
Responda SOMENTE JSON: {{"padroes": ["Rotina: ..."], "sugestoes": [{{"nome": "...", "descricao": "..."}}]}}

REGISTRO:
{registro}"""


def resumir():
    """Resume a rotina, grava padrões na memória e sugere skills (com confirmação)."""
    try:
        from ghost.ia import memoria
        linhas = [l for l in _eventos()[-MAX_LINHAS_RESUMO:] if l["app"] != "ausente" and l["segundos"] >= 30]
        if len(linhas) < 15 or not _cliente:
            return
        registro = "\n".join(f"{l['inicio']} | {l['segundos']}s | {l['app']} | {str(l.get('janela') or '')[:80]}" for l in linhas)
        r = _cliente.chat.completions.create(
            model="openai/gpt-oss-120b", messages=[{"role": "user", "content": PROMPT.format(registro=registro)}],
            temperature=0, max_tokens=1500, reasoning_effort="medium", response_format={"type": "json_object"})
        dados = json.loads(r.choices[0].message.content)
        padroes = [p for p in dados.get("padroes", []) if isinstance(p, str)]
        if padroes:
            memoria.substituir_categoria("Rotina:", padroes)
        sugestoes = [s for s in dados.get("sugestoes", [])
                     if isinstance(s, dict) and isinstance(s.get("nome"), str) and isinstance(s.get("descricao"), str)]
        if sugestoes and _falar and _pedir_confirmacao:
            for _ in range(60):  # espera até 10 min o senhor estar livre
                if not _ocupado():
                    break
                time.sleep(10)
            s = sugestoes[0]
            _pedir_confirmacao(f"Senhor, percebi uma rotina que se repete: {s['descricao']}. "
                               f"Quer que eu crie a skill {s['nome']}?",
                               lambda: _criar_skill_sugerida(s), _falar)
    except Exception as e:
        print(f"\n[ROTINA]: falha ao resumir: {e!r}")


def _criar_skill_sugerida(s):
    from ghost.ia import skills
    try:
        rascunho = skills.criar_por_descricao(f"Skill '{s['nome']}': {s['descricao']}")
        skills.salvar(rascunho)
        _falar(f"Skill {rascunho['nome']} criada. Para usar, diga: {rascunho['gatilhos'][0]}.")
    except Exception as e:
        print(f"\n[ROTINA]: não consegui criar a skill sugerida: {e!r}")
        _falar("Não consegui criar essa skill agora, senhor.")


def resumo_de_hoje():
    """Tempo por programa hoje (para 'o que eu fiz hoje?')."""
    hoje = datetime.now().strftime("%Y-%m-%d")
    tempos = {}
    for e in _eventos():
        if e["inicio"].startswith(hoje) and e["app"] != "ausente":
            tempos[e["app"]] = tempos.get(e["app"], 0) + e["segundos"]
    top = sorted(tempos.items(), key=lambda x: -x[1])[:5]
    if not top:
        return "Ainda não tenho registro de uso hoje, senhor."
    partes = [f"{a.replace('.exe', '').replace('.EXE', '')} {s // 60} minutos" for a, s in top]
    return "Hoje o senhor usou mais: " + ", ".join(partes) + "."
