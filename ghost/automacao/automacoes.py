"""
GHOST - Automações locais (as "mãos" do assistente).

Todo comando falado passa primeiro por executar(). Se for uma ação local
(abrir programa, site, WhatsApp, volume...), ela é feita aqui, sem gastar
cota de IA, e a função retorna True. Se retornar False, o app.py manda
a pergunta para a IA.
"""
import os
import re
import subprocess
import sys
import threading
import time
import unicodedata
import webbrowser
from datetime import datetime
from urllib.parse import quote_plus

import pyautogui
import requests

try:
    import pyperclip  # cola texto com acento (pyautogui.write não digita acentos)
except ImportError:
    pyperclip = None

from ghost.nucleo import caminhos, canal, preferencias

PASTA_PRINTS = caminhos.PRINTS

# Mouse num canto da tela não deve abortar teclas/cliques (FailSafeException derrubava a ação)
pyautogui.FAILSAFE = False

# -------------------------------------------------------------
# CONFIGURAÇÃO DO WHATSAPP (ajuste aqui se algo não funcionar)
# -------------------------------------------------------------
ATALHO_BUSCA_DESKTOP = ("ctrl", "f")          # busca de conversas no WhatsApp Desktop
ATALHO_BUSCA_WEB = ("ctrl", "alt", "/")       # busca de conversas no WhatsApp Web
ESPERA_ABRIR_APP = 8      # segundos aguardando a janela do app aparecer
ESPERA_CARREGAR_WEB = 6   # segundos extras para o WhatsApp Web carregar as conversas
ESPERA_RESULTADO_BUSCA = 1.5  # segundos para a busca mostrar o contato

# -------------------------------------------------------------
# UTILITÁRIOS
# -------------------------------------------------------------
def normalizar(texto):
    """minúsculas, sem acento e sem pontuação: 'Abra a Câmera.' -> 'abra a camera'"""
    texto = unicodedata.normalize("NFD", texto.lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = re.sub(r"[^\w\s]", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()

def tem(n, *termos):
    """True se algum termo aparece como palavra/expressão inteira no texto normalizado."""
    return any(re.search(rf"\b{re.escape(t)}\b", n) for t in termos)

VERBO_ABRIR = r"\b(abr\w*|abra|inici\w*|lig\w*|execut\w*|entr\w*)\b"

def pediu_abrir(n):
    return re.search(VERBO_ABRIR, n) is not None

# Gestos, macros e cadastro de gestos estão DESATIVADOS (o código continua em ghost/visao e
# ghost/automacao/macros.py). Para religar: True aqui e reinicie o Ghost.
GESTOS_ATIVOS = False
AVISO_GESTOS = "Os gestos e as macros estão desativados, senhor."


def em_segundo_plano(funcao, *args):
    """Roda em outra thread mantendo o destino da resposta (pedido do celular: a resposta volta para lá)."""
    canal.thread(funcao, *args)

def _colar(texto):
    """Cola o texto onde o cursor estiver e devolve à área de transferência o que o senhor tinha copiado."""
    if not pyperclip:
        pyautogui.write(texto, interval=0.01)  # sem pyperclip: acentos podem falhar
        return
    try:
        anterior = pyperclip.paste()
    except Exception:
        anterior = None
    pyperclip.copy(texto)
    time.sleep(0.05)
    pyautogui.hotkey("ctrl", "v")
    if anterior is not None:
        time.sleep(0.3)                    # o programa precisa ler o texto colado antes de trocar de volta
        try:
            pyperclip.copy(anterior)
        except Exception:
            pass

# -------------------------------------------------------------
# WHATSAPP
# -------------------------------------------------------------
# Quando você disser "para mim" / "para mim mesmo":
MEU_NUMERO = ""          # seu número com DDI+DDD, só dígitos (ex.: "5511999998888"). Se preenchido, é usado direto.
MEU_CONTATO = "Você"     # senão, texto pesquisado na busca do WhatsApp para achar a sua própria conversa

# Ancorada no começo e só com o verbo no imperativo: antes, "você lembra o que eu escrevi para a Deborah
# que a reunião mudou?" ENVIAVA "a reunião mudou?" para a Deborah.
REGEX_MENSAGEM = re.compile(
    r"^(?:(?:ghost|por\s+favor|pode|voc[eê])[\s,]+)*"
    r"(?:mand[ae]|envi[ae]|escrev[ae])\s+"
    r"(?:uma\s+)?(?:mensagem\s+)?(?:(?:no|pelo)\s+whats\s?app\s+(?:web\s+)?)?"
    r"(?:para|pra|pro)\s+(?:o\s+|a\s+)?"
    r"(?P<contato>[^,:]+?)[\s,:.]+"
    r"(?:dizendo|falando|escrevendo|com a mensagem|que)[\s,:.…]+"
    r"(?P<msg>.+)$",
    re.IGNORECASE,
)
PARA_MIM = {"mim", "mim mesmo", "mim mesma", "eu", "eu mesmo", "eu mesma"}

def _janelas_whatsapp(web):
    """Janelas do WhatsApp. O título pode ter contador de não lidas: '(5) WhatsApp'."""
    achadas = []
    for janela in pyautogui.getAllWindows():
        t = janela.title.strip()
        if not t or "WhatsApp" not in t:
            continue
        eh_web = any(b in t for b in ("Chrome", "Edge", "Firefox", "Opera", "Brave"))
        eh_desktop = re.fullmatch(r"(\(\d+\)\s*)?WhatsApp", t) is not None
        if (web and eh_web) or (not web and eh_desktop):
            achadas.append(janela)
    return achadas

def _titulo_em_foco():
    try:
        janela = pyautogui.getActiveWindow()
        return janela.title if janela else ""
    except Exception:
        return ""

def _trazer_para_frente(hwnd):
    """O Windows bloqueia SetForegroundWindow vindo de programa em segundo plano.
    Truque padrão: anexar a entrada de teclado à janela que está em foco antes de trocar."""
    import ctypes
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    atual = user32.GetForegroundWindow()
    tid_atual = user32.GetWindowThreadProcessId(atual, None)
    tid_meu = kernel32.GetCurrentThreadId()
    user32.AttachThreadInput(tid_atual, tid_meu, True)
    try:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)   # SW_RESTORE
        user32.keybd_event(0x12, 0, 0, 0)  # ALT pressionado: libera a troca de foco
        user32.keybd_event(0x12, 0, 2, 0)  # ALT solto
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        user32.AttachThreadInput(tid_atual, tid_meu, False)

def _focar_whatsapp(web, timeout):
    """Espera a janela existir e só retorna True se ela estiver REALMENTE em foco
    (evita digitar a mensagem em outro programa)."""
    fim = time.time() + timeout
    while True:
        if "WhatsApp" in _titulo_em_foco() and (not web or _janelas_whatsapp(True)):
            return True
        for janela in _janelas_whatsapp(web):
            try:
                _trazer_para_frente(janela._hWnd)
            except Exception:
                pass
            time.sleep(0.4)
            if "WhatsApp" in _titulo_em_foco():
                return True
        if time.time() >= fim:
            return False
        time.sleep(0.4)

def abrir_whatsapp(preferir_web=False, link="whatsapp:"):
    """Abre o WhatsApp Desktop (ou o link whatsapp:// informado); se falhar, usa o Web.
    Retorna 'desktop', 'web' ou None."""
    if not preferir_web:
        try:
            os.startfile(link)
            if _focar_whatsapp(False, ESPERA_ABRIR_APP):
                time.sleep(0.6)  # deixa a interface terminar de desenhar
                return "desktop"
        except OSError:
            pass
    if _focar_whatsapp(True, 0.5):  # já existe uma aba do WhatsApp Web em uso
        return "web"
    webbrowser.open("https://web.whatsapp.com")
    if _focar_whatsapp(True, 20):
        time.sleep(ESPERA_CARREGAR_WEB)
        return "web"
    return None

def enviar_whatsapp(contato, mensagem, preferir_web, falar):
    try:
        para_mim = normalizar(contato) in PARA_MIM
        nome_falado = "o senhor mesmo" if para_mim else contato

        # Caminho direto: número conhecido -> abre a conversa já com o texto digitado
        if para_mim and MEU_NUMERO and not preferir_web:
            link = f"whatsapp://send?phone={MEU_NUMERO}&text={quote_plus(mensagem)}"
            if abrir_whatsapp(False, link) == "desktop":
                time.sleep(1.0)
                if "WhatsApp" not in _titulo_em_foco():
                    falar("Senhor, perdi o foco do WhatsApp. Mensagem não enviada.")
                    return
                pyautogui.press("enter")
                print(f"\n[AUTOMAÇÃO]: WhatsApp (link) -> {MEU_NUMERO}: {mensagem}")
                falar(f"Mensagem enviada para {nome_falado}, senhor.")
                return

        modo = abrir_whatsapp(preferir_web)
        if not modo:
            falar("Senhor, não consegui abrir o WhatsApp em primeiro plano.")
            return
        busca = MEU_CONTATO if para_mim else contato
        atalho = ATALHO_BUSCA_WEB if modo == "web" else ATALHO_BUSCA_DESKTOP

        pyautogui.press("esc")
        pyautogui.hotkey(*atalho)
        time.sleep(0.5)
        pyautogui.hotkey("ctrl", "a")
        _colar(busca)
        time.sleep(ESPERA_RESULTADO_BUSCA)
        pyautogui.press("enter")          # abre a 1ª conversa encontrada
        time.sleep(1.0)
        if "WhatsApp" not in _titulo_em_foco():  # trava de segurança antes de digitar
            falar("Senhor, perdi o foco do WhatsApp. Mensagem não enviada.")
            return
        _colar(mensagem)
        time.sleep(0.2)
        pyautogui.press("enter")          # envia
        print(f"\n[AUTOMAÇÃO]: WhatsApp ({modo}) -> {busca}: {mensagem}")
        falar(f"Mensagem enviada para {nome_falado}, senhor.")
    except Exception as e:
        print(f"\n[AUTOMAÇÃO]: Falha no WhatsApp: {e}")
        falar("Senhor, houve uma falha ao enviar a mensagem.")

def _tratar_whatsapp(texto, n, falar):
    m = REGEX_MENSAGEM.search(texto)
    if m:
        contato = re.sub(r"\s+(?:no|pelo)\s+whats\s?app(?:\s+web)?$", "", m.group("contato").strip(" ,.:"), flags=re.I)
        from ghost.ia import pessoas
        contato = pessoas.resolver_contato(contato)  # "minha líder" -> "Deborah"
        mensagem = m.group("msg").strip(" .…")
        preferir_web = tem(n, "whatsapp web", "whats app web")
        falar("Enviando, senhor." if normalizar(contato) in PARA_MIM else f"Enviando para {contato}.")
        em_segundo_plano(enviar_whatsapp, contato, mensagem, preferir_web, falar)
        return True
    if tem(n, "whatsapp", "whats app") and pediu_abrir(n):
        preferir_web = tem(n, "whatsapp web", "whats app web")
        falar("Abrindo o WhatsApp, senhor.")
        em_segundo_plano(abrir_whatsapp, preferir_web)
        return True
    return False

# -------------------------------------------------------------
# DITADO POR VOZ E TECLAS
# -------------------------------------------------------------
# "digite bom dia equipe" / "escreva o texto reunião às 14h" -> escreve onde o cursor estiver
REGEX_DITADO = re.compile(
    r"^(?:(?:por\s+favor|voc[eê]|pode|ghost)[\s,]+)*(?:digit[ae]|digitar|escrev[ae](?:\s+aqui)?)[\s,:]+"
    r"(?:(?:a\s+frase|o\s+texto|isso|isto)[\s,:]+)?(?P<t>.+)$",
    re.IGNORECASE,
)
# "aperte enter", "pressione tab", "tecla esc"
TECLAS_FALADAS = {
    "enter": "enter", "entra": "enter", "tab": "tab", "esc": "esc", "escape": "esc",
    "apagar": "backspace", "backspace": "backspace", "delete": "delete", "deletar": "delete",
    "espaco": "space", "seta para cima": "up", "seta para baixo": "down",
    "seta para esquerda": "left", "seta para direita": "right",
    "copiar": ("ctrl", "c"), "colar": ("ctrl", "v"), "desfazer": ("ctrl", "z"),
    "selecionar tudo": ("ctrl", "a"), "salvar": ("ctrl", "s"),
}
REGEX_TECLA = re.compile(r"^(?:aperte|aperta|pressione|pressiona|tecla|clique em)\s+(?:o\s+|a\s+)?(?P<k>.+)$")

def _tratar_ditado_e_teclas(texto, n, falar):
    m = REGEX_DITADO.search(texto.strip())
    # "escreva um e-mail para o Gustavo..." é um PEDIDO (vai para a IA), não um ditado para colar na tela
    if m and not re.match(r"(?i)(?:um|uma)\s+(?:e-?mail|mensagem|texto|poema|resumo|relat[oó]rio|carta)\b",
                          m.group("t").strip()):
        conteudo = m.group("t").strip()
        if conteudo.endswith(".") and conteudo.count(".") == 1:  # ponto final que o Whisper põe sozinho
            conteudo = conteudo[:-1]
        time.sleep(0.3)  # dá tempo de soltar o F9
        _colar(conteudo)
        print(f"\n[AUTOMAÇÃO]: digitado -> {conteudo}")
        return True
    m = REGEX_TECLA.search(n)
    if m and m.group("k") in TECLAS_FALADAS:
        tecla = TECLAS_FALADAS[m.group("k")]
        if isinstance(tecla, tuple):
            pyautogui.hotkey(*tecla)
        else:
            pyautogui.press(tecla)
        print(f"\n[AUTOMAÇÃO]: tecla -> {m.group('k')}")
        return True
    return False

# -------------------------------------------------------------
# PROGRAMAS E SITES
# -------------------------------------------------------------
PROGRAMAS = {
    "calculadora": ("calc.exe", "a calculadora"),
    "bloco de notas": ("notepad.exe", "o Bloco de Notas"),
    "gerenciador de tarefas": ("taskmgr.exe", "o Gerenciador de Tarefas"),
    "explorador de arquivos": ("explorer.exe", "o Explorador de Arquivos"),
}

SITES = {
    "google": "https://www.google.com",
    "youtube": "https://www.youtube.com",
    "gmail": "https://mail.google.com",
}
NOMES_SITES = {"google": "Google", "youtube": "YouTube", "gmail": "Gmail"}

# "pesquise X no YouTube", "pesquisa no Google X", "procure X", "busque por X"
REGEX_PESQUISA = re.compile(
    r"^(?:(?:por\s+favor|voc[eê]|vc|pode|poderia|consegue|me|ghost)[\s,]+)*"  # só no início da frase
    r"(?:pesquis\w*|procur\w*|busc\w*|busqu\w*)\s+"
    r"(?:(?:no|na)\s+(?P<site1>google|youtube|internet|web)\s+)?"
    r"(?:(?:por|sobre)\s+)?"
    r"(?P<q>.+?)"
    r"(?:\s+(?:no|na)\s+(?P<site2>google|youtube|internet|web))?"
    r"[\s.?!]*$",
    re.IGNORECASE,
)

def _tratar_programas_e_sites(texto, n, falar):
    m = REGEX_PESQUISA.search(texto.strip())
    if m and m.group("q").strip():
        q = m.group("q").strip()
        site = (m.group("site1") or m.group("site2") or "google").lower()
        url = (f"https://www.youtube.com/results?search_query={quote_plus(q)}" if site == "youtube"
               else f"https://www.google.com/search?q={quote_plus(q)}")
        webbrowser.open(url)
        falar(f"Pesquisando {q} no {'YouTube' if site == 'youtube' else 'Google'}, senhor.")
        return True

    if not pediu_abrir(n):
        return False

    for nome, (exe, artigo) in PROGRAMAS.items():
        if tem(n, nome):
            subprocess.Popen([exe])
            falar(f"Abrindo {artigo}, senhor.")
            return True

    if tem(n, "chrome", "navegador"):
        os.system('start "" chrome')
        falar("Abrindo o Chrome, senhor.")
        return True

    for nome, url in SITES.items():
        if tem(n, nome):
            webbrowser.open(url)
            falar(f"Abrindo o {NOMES_SITES[nome]}, senhor.")
            return True
    return False

# -------------------------------------------------------------
# SISTEMA, MÍDIA E UTILITÁRIOS
# -------------------------------------------------------------
def obter_localizacao_ip():
    try:
        res = requests.get("http://ip-api.com/json/", timeout=3).json()
        if res.get("status") == "success":
            return f"{res.get('city', '')}, {res.get('regionName', '')} - {res.get('country', '')}"
    except Exception:
        pass
    return None

def _tratar_sistema(n, falar):
    curto = len(n.split()) <= 5  # comandos de mídia só valem em frases curtas

    if tem(n, "camera", "gestos") and re.search(r"\b(fech\w*|deslig\w*|desativ\w*|pare|parar|pausa\w*|ativ\w*|abr\w*|abra|lig\w*|inici\w*)\b", n):
        if not GESTOS_ATIVOS:
            falar(AVISO_GESTOS)
            return True
        from ghost.visao.gestos import alternar_camera
        if re.search(r"\b(fech\w*|deslig\w*|desativ\w*|pare|parar|pausa\w*)\b", n):   # "par\w*" pegava "para"
            alternar_camera(False, falar_callback=falar, executar_comando=lambda f: executar(f, falar))
            return True
        if re.search(r"\b(ativ\w*|abr\w*|abra|lig\w*|inici\w*)\b", n):
            alternar_camera(True, falar_callback=falar, executar_comando=lambda f: executar(f, falar))
            return True

    if tem(n, "aumentar volume", "aumenta o volume", "aumentar o volume", "sobe o volume"):
        for _ in range(5):
            pyautogui.press("volumeup")
        falar("Volume aumentado, senhor.")
        return True
    if tem(n, "diminuir volume", "diminui o volume", "diminuir o volume", "abaixa o volume"):
        for _ in range(5):
            pyautogui.press("volumedown")
        falar("Volume diminuído, senhor.")
        return True
    if curto and tem(n, "mutar", "silenciar", "desmutar"):
        pyautogui.press("volumemute")
        falar("Áudio alterado, senhor.")
        return True
    if curto and tem(n, "pausar", "despausar", "reproduzir", "play", "pause"):
        pyautogui.press("playpause")
        return True
    if curto and tem(n, "proxima musica", "proxima faixa"):
        pyautogui.press("nexttrack")
        return True
    if curto and tem(n, "musica anterior", "faixa anterior"):
        pyautogui.press("prevtrack")
        return True

    if _pedido_de_print(n):
        _tirar_print(n, falar)
        return True

    if tem(n, "onde estou", "onde estamos", "minha localizacao", "qual a localizacao"):
        local = obter_localizacao_ip()
        falar(f"Estamos localizados em {local}, senhor." if local else "Localização indisponível no momento, senhor.")
        return True

    if curto and tem(n, "fechar janela", "fecha a janela", "feche a janela"):
        pyautogui.hotkey("alt", "f4")
        return True

    if tem(n, "cancelar desligamento", "cancela o desligamento"):
        os.system("shutdown /a")
        falar("Desligamento cancelado, senhor.")
        return True
    # só a ordem direta: "como faço para não desligar o computador..." não pode desligar o PC
    if re.fullmatch(r"(?:ghost )?(?:desliga|desligar|desligue) (?:o )?(?:computador|pc)(?: agora)?", n):
        falar("Desligando em 30 segundos. Diga cancelar desligamento para abortar, senhor.")
        os.system("shutdown /s /t 30")
        return True
    return False

# -------------------------------------------------------------
# GHOST: CADASTRO DE GESTOS E MONITORES (desativados: GESTOS_ATIVOS)
# -------------------------------------------------------------
def abrir_cadastro(falar):
    """Libera a câmera, abre a tela de cadastro e devolve a câmera quando ela fechar."""
    from ghost.visao import camera
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pyw):
        pyw = sys.executable
    suspensos = camera.suspender_todos()
    try:
        proc = subprocess.Popen([pyw, "-m", "ghost.visao.cadastro_gestos"], cwd=caminhos.RAIZ)
    except Exception:
        camera.retomar_todos()
        raise
    falar("Abrindo o cadastro de gestos, senhor.")
    def _esperar():
        try:
            proc.wait()
        finally:
            camera.retomar_todos()
        if suspensos:
            print("\n[AUTOMAÇÃO]: cadastro fechado, câmera devolvida ao Ghost.")
    threading.Thread(target=_esperar, daemon=True, name="cadastro-gestos").start()

def _minutos_falados(n):
    if tem(n, "meia hora"):
        return 30
    m = re.search(r"\b(\d+)\s*(minuto|hora)", n)
    if m:
        return int(m.group(1)) * (60 if m.group(2) == "hora" else 1)
    if tem(n, "uma hora", "1 hora"):
        return 60
    if tem(n, "duas horas"):
        return 120
    return 60

VERBO_DESLIGAR = r"\b(desativ\w*|deslig\w*|pare|parar|pausa\w*|encerr\w*)\b"
VERBO_LIGAR = r"\b(ativ\w*|lig\w*|retom\w*|volt\w*|inici\w*)\b"

def _executar_acao_cadastrada(n, falar):
    """'executar ação abrir relatório' -> roda a ação de mesmo nome do cadastro (macro, tecla ou comando)."""
    m = re.search(r"\b(?:execut\w*|rod\w*|fac[ae])\s+(?:a\s+)?(?:acao|macro)\s+(?P<nome>.+)$", n)
    if not m:
        return False
    if not GESTOS_ATIVOS:
        falar(AVISO_GESTOS)
        return True
    from ghost.automacao import macros
    from ghost.visao import gestos_lib as gl
    alvo = m.group("nome").strip()
    acoes = [a for a in gl.carregar_cadastro()["acoes"] if a["tipo"] in ("macro", "tecla", "comando")]
    achada = next((a for a in acoes if normalizar(a["nome"]) == alvo), None) or \
             next((a for a in acoes if alvo in normalizar(a["nome"]) or normalizar(a["nome"]) in alvo), None)
    if not achada:
        falar(f"Senhor, não encontrei a ação {alvo} no cadastro.")
        return True
    falar(f"Executando {achada['nome']}, senhor.")
    if achada["tipo"] == "macro":
        def _rodar():
            time.sleep(1.5)  # tempo da fala e de soltar o F9
            macros.executar(achada.get("passos", []), achada.get("ritmo", "original"))
        em_segundo_plano(_rodar)
    elif achada["tipo"] == "tecla":
        pyautogui.hotkey(*achada["valor"].split("+"))
    else:
        executar(achada["valor"], falar)
    return True

# -------------------------------------------------------------
# SKILLS ENSINADAS POR VOZ E OBSERVAÇÃO DA ROTINA
# -------------------------------------------------------------
_aguardando_descricao = 0.0   # momento em que o Ghost pediu a descrição de uma skill

def _montar_skill(descricao, falar):
    from ghost.ia import skills
    def _trabalho():
        try:
            r = skills.criar_por_descricao(descricao)
        except Exception as e:
            falar(f"Senhor, não consegui montar essa skill: {e}.")
            return
        extra = (" Não consigo fazer: " + "; ".join(r["nao_suportado"]) + ".") if r.get("nao_suportado") else ""
        pedir_confirmacao(f"Entendi a skill {r['nome']}: {r['resumo']}. Para usar, diga {r['gatilhos'][0]}.{extra} "
                          "Posso salvar?", lambda: (skills.salvar(r), falar("Skill salva, senhor.")), falar)
    falar("Montando a skill, um instante.")
    em_segundo_plano(_trabalho)

def _ao_terminar_gravacao(falar):
    def fim(r):
        n = len(r["passos"])
        if not n:
            falar("Senhor, não gravei nenhum passo. Diga aprenda uma skill pela tela para tentar de novo.")
            return
        try:
            from ghost.nucleo import painel
            painel.abrir_janela(revisao=True)
        except Exception:
            pass
        datas = sum(1 for p in r["passos"] if p.get("tipo") == "data")
        extra = (f" Achei {datas} campo{'s' if datas > 1 else ''} de data: na hora de rodar, uso o período que o senhor "
                 "pedir." if datas else "")
        if any("calendário" in a for a in r.get("avisos", [])):
            extra += " Atenção: alguns passos escolhem o dia no calendário; isso não repete bem. Veja o aviso no painel."
        falar(f"Gravei {n} passo{'s' if n > 1 else ''}, senhor.{extra} A revisão está no painel. "
              "Diga teste a skill, ou salve a skill como, e o nome.")
    return fim


def _numero(n):
    m = re.search(r"\bpasso\s+(\d+|um|dois|tres|quatro|cinco|seis|sete|oito|nove|dez)\b", n)
    if not m:
        return None
    v = m.group(1)
    return int(v) if v.isdigit() else ["um", "dois", "tres", "quatro", "cinco", "seis", "sete", "oito", "nove", "dez"].index(v) + 1


def _tratar_demonstracao(texto, n, falar):
    from ghost.automacao import demonstracao as demo
    if tem(n, "pela tela", "olhando a tela", "vendo a tela", "por demonstracao", "vou te mostrar", "vou mostrar",
           "grave uma skill", "gravar uma skill", "gravar skill", "grava uma skill", "gravar isso", "grava isso",
           "grave isso", "aprenda isso", "aprende isso") and \
            re.search(r"\b(skill|habilidade|mostr\w*|grav\w*|isso)\b", n):
        demo.iniciar_gravacao(falar, _ao_terminar_gravacao(falar))
        return True
    if demo.gravando() and tem(n, "parar de gravar", "pare de gravar", "para de gravar", "terminei", "pode parar",
                                 "fim da gravacao", "acabei"):
        demo.parar_gravacao()
        falar("Gravação encerrada. Montando os passos, um instante.")
        return True
    if not demo.rascunho():
        return False
    if tem(n, "teste a skill", "testar a skill", "testa a skill", "teste a gravacao", "testar skill"):
        r = demo.rascunho()
        falar("Testando, senhor. Não mexa no mouse; F10 interrompe.")
        em_segundo_plano(lambda: demo.executar({"nome": "teste", "passos": r["passos"]}, falar,
                                               lambda q: perguntar(q, falar), teste=True, frase=texto))
        return True
    m = re.search(r"\b(?:salv\w*|grav\w*)\s+(?:a\s+)?(?:skill|habilidade)\s+(?:como|com o nome(?: de)?|chamada)\s+(?P<nome>.+)$", n)
    if m or tem(n, "salvar a skill", "salve a skill", "salva a skill"):
        if m:
            demo.definir_nome(m.group("nome"))
        try:
            s = demo.salvar()
            falar(f"Skill {s['nome']} salva, senhor. Para usar, diga {s['gatilhos'][0]}.")
        except ValueError as e:
            falar(f"Senhor, {e}.")
        return True
    if tem(n, "descarte a skill", "descartar a skill", "descarta a skill", "apague a gravacao", "jogue fora a skill"):
        demo.descartar()
        falar("Gravação descartada, senhor.")
        return True
    k = _numero(n)
    if k and re.search(r"\b(remov\w*|apag\w*|tir\w*|exclu\w*)\b", n):
        falar(f"Passo {k} removido, senhor." if demo.remover_passo(k) else f"Senhor, não há passo {k} que eu possa remover.")
        return True
    if k and re.search(r"\b(muda|variavel|varia|pergunt\w*)\b", n):
        falar(f"Certo: o passo {k} será perguntado na hora." if demo.marcar_variavel(k)
              else f"Senhor, o passo {k} não é de digitação.")
        return True
    if tem(n, "mostre a revisao", "abrir a revisao", "abra a revisao", "revisar a skill", "revisao da skill"):
        from ghost.nucleo import painel
        painel.abrir_janela(revisao=True)
        falar("A revisão está no painel, senhor.")
        return True
    return False


def _quer_mostrar(n):
    """Resposta a 'mostrar na tela ou descrever?' que escolhe a tela. Aceita 'tela' grudada em outra palavra
    (a voz já transcreveu 'na tela' como 'Renatella')."""
    return bool(re.search(r"\b(mostr\w*|grav\w*|ver|veja|olh\w*|observ\w*|assist\w*)\b|tel+a", n))


NUMEROS = {"um": 1, "uma": 1, "primeiro": 1, "dois": 2, "segundo": 2, "tres": 3, "terceiro": 3}


def _pedido_de_print(n):
    return bool(re.search(r"\b(print|printa|printe|screenshot|captura de tela|capturar a tela|capturar tela)\b", n)) \
        and not re.search(r"\b(impress\w*|imprim\w*)\b", n) and not n.startswith(("como ", "o que ", "qual "))


def _tirar_print(n, falar):
    """Salva o print em prints/. Pedido do celular: manda a imagem para o app (um por monitor, ou o monitor pedido)."""
    from ghost.visao import olho
    m = re.search(r"\b(?:monitor|tela)\s+(\d|um|uma|dois|tres|primeiro|segundo|terceiro)\b", n)
    qual = (int(m.group(1)) if m.group(1).isdigit() else NUMEROS[m.group(1)]) if m else None
    try:
        total = len(olho.monitores())
    except Exception:
        total = 1
    if qual and qual > total:
        falar(f"Senhor, só há {total} monitor{'es' if total > 1 else ''}.")
        return
    numeros = [qual] if qual else list(range(1, total + 1))
    os.makedirs(PASTA_PRINTS, exist_ok=True)
    pedido_do_celular = canal.atual() is not None
    for k in numeros:
        img = olho.capturar_monitor(k) if total > 1 or qual else pyautogui.screenshot()
        if img is None:
            continue
        img.save(os.path.join(PASTA_PRINTS, f"print_{datetime.now():%Y%m%d_%H%M%S}_m{k}.png"))
        if pedido_do_celular:
            from ghost.nucleo import painel
            painel.imagem_celular(img, f"Monitor {k}" if total > 1 else "Tela")
    if pedido_do_celular:
        falar("Aqui está, senhor." if len(numeros) == 1 else f"Aqui estão os {len(numeros)} monitores, senhor.")
    else:
        falar("Captura realizada, senhor.")


def _tratar_skills(texto, n, falar):
    global _aguardando_descricao
    from ghost.ia import skills
    from ghost.servicos import rotina
    # resposta ao "descreva a skill"
    if _aguardando_descricao and time.time() - _aguardando_descricao < 120:
        _aguardando_descricao = 0.0
        if re.search(r"\b(na|pela|minha) tela\b|\bmostr\w*|\bveja\b", n) and len(n.split()) < 14:      # mudou de ideia: "eu falei que quero que você veja na tela"
            from ghost.automacao import demonstracao
            demonstracao.iniciar_gravacao(falar, _ao_terminar_gravacao(falar))
            return True
        _montar_skill(texto, falar)
        return True
    m = re.search(r"^(?:ghost\s+)?(?:(?:eu\s+)?(?:quero|queria|gostaria)\s+(?:que\s+)?(?:voce\s+|vc\s+)?|vamos\s+|pode\s+)?"
                  r"(?:aprend\w*|cri\w*|ensin\w*|cadastr\w*)\s+(?:uma\s+)?(?:nova\s+)?"
                  r"(?:skill|habilidade|rotina automatica)\b[\s,:]*(?P<desc>.*)$", n)
    if m:
        desc_original = re.split(r"(?i)\b(?:skill|habilidade|rotina autom[aá]tica)\b[\s,:]*", texto, maxsplit=1)
        desc = desc_original[1].strip() if len(desc_original) > 1 else ""
        if len(desc.split()) < 4:
            def _como():
                r = perguntar("Prefere me mostrar na tela ou descrever os passos, senhor?", falar, tempo=60)
                if r is not None and not _quer_mostrar(normalizar(r)) and len(r.split()) < 6 \
                        and not re.search(r"\b(descrev\w*|falar|explic\w*|ditar|dito)\b", normalizar(r)):
                    # resposta que não deu para entender (voz trocou as palavras): pergunta de novo, curto
                    r = perguntar("Na tela ou descrevendo, senhor?", falar, tempo=45)
                if r is None:
                    falar("Tudo bem, senhor.")
                    return
                if _quer_mostrar(normalizar(r)):
                    from ghost.automacao import demonstracao
                    demonstracao.iniciar_gravacao(falar, _ao_terminar_gravacao(falar))
                elif len(r.split()) >= 6:                        # já veio a descrição
                    _montar_skill(r, falar)
                else:
                    global _aguardando_descricao
                    _aguardando_descricao = time.time()
                    falar("Pode descrever, senhor: o nome, a frase que vai disparar e os passos.")
            em_segundo_plano(_como)
        else:
            _montar_skill(desc, falar)
        return True
    m = re.search(r"^(?:ghost\s+)?(?:mostr\w*|descrev\w*|expliqu\w*|como funciona)\s+(?:a\s+)?(?:skill|habilidade)\s+(?P<nome>.+)$", n)
    if m:
        alvo = skills.normalizar(m.group("nome"))
        s = next((x for x in skills.carregar() if skills.normalizar(x["nome"]) == alvo), None) or \
            next((x for x in skills.carregar() if alvo in skills.normalizar(x["nome"])), None)
        if not s:
            falar("Senhor, não encontrei essa skill.")
            return True
        if s.get("tipo") == "demonstracao":
            from ghost.automacao import demonstracao
            passos = [demonstracao.descrever(p) for p in s["passos"]]
        else:
            passos = [f"{p.get('ferramenta')} {p.get('args', {})}" for p in s["passos"]]
        falar(f"A skill {s['nome']} tem {len(passos)} passos: " + "; ".join(f"{i}, {d}" for i, d in enumerate(passos[:8], 1))
              + ("; e outros." if len(passos) > 8 else "."))
        return True
    if tem(n, "quais skills", "que skills", "lista de skills", "minhas skills", "quais habilidades"):
        lista = skills.carregar()
        falar(("Skills salvas: " + "; ".join(f"{s['nome']}, dita como {s['gatilhos'][0]}" for s in lista) + ".")
              if lista else "Ainda não há skills salvas, senhor.")
        return True
    m = re.search(r"^(?:ghost\s+)?(?:esquec\w*|apag\w*|exclu\w*|remov\w*)\s+(?:a\s+)?(?:skill|habilidade)\s+"
                  r"(?P<nome>.+)$", n)
    if m:
        r = skills.excluir(m.group("nome"))
        if isinstance(r, list):          # mais de uma parecida: não apaga nenhuma, pergunta qual
            falar("Senhor, há mais de uma skill parecida: " + ", ".join(r) + ". Diga o nome completo.")
        else:
            falar("Skill excluída, senhor." if r else "Senhor, não encontrei essa skill.")
        return True
    s = skills.encontrar(n)
    if s:
        falar(f"Executando {s['nome']}, senhor.")
        em_segundo_plano(lambda: skills.executar(s, falar, pedir_confirmacao, frase=texto))
        return True

    # observação da rotina
    if tem(n, "observacao da rotina", "observar a rotina", "observar minha rotina", "aprender minha rotina",
           "monitorar minha rotina"):
        if re.search(VERBO_DESLIGAR, n):
            rotina.ativar(False, falar); return True
        if re.search(VERBO_LIGAR, n) or tem(n, "observar", "aprender", "monitorar"):
            rotina.ativar(True, falar); return True
    if tem(n, "o que eu fiz hoje", "o que fiz hoje", "como foi meu dia", "resumo do meu dia"):
        falar(rotina.resumo_de_hoje())
        return True
    return False

# -------------------------------------------------------------
# FICHAS DE PESSOAS (sem biometria: só o que for dito)
# -------------------------------------------------------------
REGEX_APRESENTAR = re.compile(r"^(?:ghost\s+)?(?:(?:este|esta|esse|essa)\s+(?:e|eh)\s+(?:o|a)\s+|"
                              r"(?:te\s+)?apresent\w*\s+(?:o|a)\s+|conhec\w*\s+(?:o|a)\s+|"
                              r"anot\w*\s+(?:sobre|que)\s+(?:o|a)\s+)")
REGEX_FALANTE = re.compile(r"^(?:ghost\s+)?(?:aqui\s+(?:e|eh)|sou|quem\s+esta\s+falando\s+(?:e|eh)|"
                           r"agora\s+(?:e|eh|quem\s+fala\s+e))\s+(?:o\s+|a\s+)?(?P<nome>[a-z]+(?:\s+[a-z]+)?)$")
REGEX_CONSULTA = re.compile(r"(?:o\s+que\s+(?:voce\s+)?sabe\s+(?:sobre|d[oa])|ficha\s+d[oa]|quem\s+(?:e|eh))\s+"
                            r"(?:o\s+|a\s+)?(?P<nome>.+)$")
REGEX_ESQUECER = re.compile(r"^(?:ghost\s+)?(?:esquec\w*|apag\w*|exclu\w*)\s+(?:a\s+)?ficha\s+d[oa]\s+(?P<nome>.+)$")
# palavras que vêm depois de "sou/aqui é" mas não são nome ("sou do PCP", "aqui é muito quente")
NAO_NOME = {"eu", "ele", "ela", "voce", "o", "a", "dono", "do", "da", "de", "muito", "bem", "mais", "um", "uma",
            "responsavel", "novo", "nova", "eu mesmo", "so", "quem"}

def _tratar_pessoas(texto, n, falar):
    from ghost.ia import pessoas
    m = REGEX_FALANTE.search(n)
    if m and len(n.split()) <= 6 and m.group("nome").split()[0] not in NAO_NOME:
        p = pessoas.definir_falante(m.group("nome"))
        if p is None:
            falar(f"Bem-vindo de volta, {pessoas.DONO}.")
        else:
            falar(f"Olá, {p['nome']}." + ("" if p.get("funcao") or p.get("notas") else
                                           " Ainda não tenho uma ficha sua. Quer se apresentar?"))
        return True
    if REGEX_APRESENTAR.search(n):
        def _salvar():
            try:
                p = pessoas.registrar(texto)
                falar(f"Ficha de {p['nome']} salva" + (f": {p['funcao']}." if p.get("funcao") else "."))
            except Exception as e:
                falar(f"Não consegui registrar: {e}.")
        em_segundo_plano(_salvar)
        return True
    m = REGEX_ESQUECER.search(n)
    if m:
        falar("Ficha excluída." if pessoas.excluir(m.group("nome")) else "Não encontrei essa ficha.")
        return True
    m = REGEX_CONSULTA.search(n)
    if m and m.group("nome") not in ("mim", "voce", "eu"):
        p = pessoas.buscar(m.group("nome")) or pessoas.buscar(pessoas.resolver_contato(m.group("nome")))
        if p:
            falar(pessoas.descrever(p))
            return True
    return False

def _tratar_resumo(texto, n, falar):
    from ghost.servicos import resumo
    if (n in ("bom dia", "bom dia ghost", "ghost bom dia") or
            tem(n, "resumo do dia", "resumo da manha", "resumo de hoje", "como esta o meu dia")):
        em_segundo_plano(lambda: falar(resumo.gerar()))
        return True
    if tem(n, "previsao do tempo", "como esta o tempo", "como esta o clima", "vai chover") and len(n.split()) <= 8:
        def _clima():
            try:
                falar(resumo.clima())
            except Exception:
                falar("Senhor, não consegui consultar o clima agora.")
        em_segundo_plano(_clima)
        return True
    m = re.search(r"\bminha cidade (?:e|eh|agora e)\s+(?P<c>.+)$", n)
    if m:
        cidade = re.split(r"(?i)\bminha cidade (?:é|e|agora é)\s+", texto, maxsplit=1)[-1].strip(" .!")
        preferencias.definir("cidade", cidade)
        falar(f"Certo, senhor. Vou usar {cidade} para o clima.")
        return True
    return False

def _tratar_alertas(n, falar):
    from ghost.servicos import alertas
    if tem(n, "alertas", "avisos"):
        if tem(n, "silenci", "silenciar", "silencie") or re.search(r"\b(?:por|durante)\s+\d+|meia hora|uma hora", n):
            alertas.silenciar(_minutos_falados(n), falar); return True
        if re.search(VERBO_DESLIGAR, n):
            alertas.ligar(False, falar); return True
        if re.search(VERBO_LIGAR, n):
            alertas.ligar(True, falar); return True
    if tem(n, "como esta o computador", "como esta o pc", "status do computador", "status do pc", "saude do pc"):
        falar(alertas.situacao()); return True
    return False

def _tratar_personalidade(n, falar):
    if tem(n, "modo serio", "modo objetivo", "seja mais objetivo", "sem gracinha", "sem piadas"):
        preferencias.definir("personalidade", "objetivo"); falar("Entendido, senhor. Modo objetivo."); return True
    if tem(n, "modo jarvis", "modo normal", "pode brincar", "volte ao normal", "personalidade normal"):
        preferencias.definir("personalidade", "jarvis"); falar("Às suas ordens, senhor. De volta ao normal."); return True
    return False

def _tratar_hud(n, falar):
    # telas de visualização: "mostre o link neural da rede", "abra o mapa da rede"
    # só ABRIR: frase curta com verbo de mostrar. "crie departamentos no link neural" vai para a IA (não reabre a tela)
    if (tem(n, "link neural", "mapa da rede", "mapa de rede", "hud da rede", "tela da rede", "rede neural da rede",
            "visualizar a rede", "mostrar a rede", "mostre a rede", "mostra a rede", "desenhe a rede")
            and len(n.split()) <= 9
            and not re.search(r"\b(cri\w*|departament\w*|setor\w*|renome\w*|nome\w*|apelid\w*|coloc\w*|"
                              r"coloq\w*|ponha|poe|mud\w*|troc\w*|remov\w*|adicion\w*|marc\w*)\b", n)):
        from ghost.nucleo import painel
        if painel.abrir_hud("rede"):
            falar("Abrindo o link neural da rede, senhor.")
        else:
            falar("Senhor, o painel não está ligado; não consegui abrir o mapa da rede.")
        return True
    # "exportar indicadores": Excel com tudo o que a tela de indicadores mostra
    if tem(n, "exportar indicadores", "exporta os indicadores", "exportar os indicadores", "exportar painel",
           "exportar o painel", "exportar relatorio do painel", "exportar relatorio dos indicadores",
           "gerar relatorio dos indicadores", "exportar metricas"):
        from ghost.nucleo import painel

        def _exportar():
            try:
                caminho = painel.exportar()
                falar(f"Pronto, senhor. Exportei os indicadores para Documentos, Ghost, Relatórios: {os.path.basename(caminho)}.")
            except Exception as e:
                falar(f"Senhor, não consegui exportar os indicadores: {e}.")
        em_segundo_plano(_exportar)
        return True
    # demonstração do painel (dados de exemplo, para mostrar a alguém)
    if tem(n, "demonstracao do painel", "demonstracao do ghost", "demonstracao do hud", "modo demonstracao", "modo demo",
           "painel de demonstracao", "painel demo", "abrir demonstracao", "abra a demonstracao", "criar demonstracao",
           "crie uma demonstracao", "cria uma demonstracao", "fazer uma demonstracao", "faca uma demonstracao"):
        from ghost.nucleo import painel
        caminho = painel.criar_demonstracao()
        falar("Abri a demonstração do painel, senhor. Os arquivos ficaram em Documentos, Ghost, Demonstração.")
        print(f"\n[PAINEL]: demonstração em {caminho}")
        return True
    # app do celular: pareamento (QR + código) no painel, PIN, aparelhos
    if tem(n, "celular", "qr code", "qrcode", "qr", "pin do celular", "aparelhos pareados"):
        from ghost.nucleo import celular, painel
        if tem(n, "trocar pin", "troca o pin", "trocar o pin", "esqueci o pin", "novo pin", "apagar o pin"):
            celular.trocar_pin()
            falar("PIN apagado e todos os celulares removidos, senhor. Para usar de novo, diga conectar celular.")
            return True
        if tem(n, "remover os celulares", "remover celulares", "remover todos os celulares", "esquecer os celulares",
               "remover os aparelhos", "remover aparelhos", "desparear"):
            celular.remover_todos(); falar("Todos os celulares foram removidos, senhor."); return True
        if re.search(r"\b(deslig\w*|desconect\w*|desativ\w*|bloque\w*)\b", n):
            celular.desativar(); falar("Acesso pelo celular desligado, senhor."); return True
        if tem(n, "conectar celular", "conectar o celular", "conectar meu celular", "app do celular", "aplicativo do celular",
               "usar no celular", "abrir no celular", "qr code", "qrcode", "codigo do celular", "ghost no celular",
               "parear celular", "parear o celular", "parear meu celular", "novo codigo", "parear outro celular"):
            try:
                r = celular.ativar()
                painel.abrir_janela(mostrar_qr=True)
                via = "pelo Tailscale, inclusive no 5G" if r["modo"] == "tailscale" else "só no mesmo Wi-Fi, sem criptografia"
                falar(f"O código de pareamento está no painel, senhor, válido por 5 minutos. Acesso {via}.")
            except celular.ErroCelular as e:
                falar(f"Senhor, {e}")
            return True
    # a FAIXA do topo (o que o Ghost está fazendo agora)
    if tem(n, "faixa", "hud"):
        from ghost.nucleo import hud
        if re.search(r"\b(escond\w*|ocult\w*|tir\w*|deslig\w*|fech\w*)\b", n):
            hud.mostrar(False); falar("Faixa escondida, senhor."); return True
        if re.search(r"\b(mostr\w*|exib\w*|lig\w*|abr\w*|volt\w*)\b", n):
            hud.mostrar(True); falar("Faixa visível, senhor."); return True
    # a TELA de indicadores (só a DO GHOST: "abra o painel de controle" é do Windows)
    outro_painel = re.search(r"\bpainel d[aeo]s?\b(?!\s+ghost)", n)          # "painel de controle", "painel da produção"
    n_painel = re.sub(r"^(?:(?:eu|ja|so)\s+)*(?:falei|disse|pedi|mandei)\s+(?:para\s+|pra\s+)?", "", n)  # "eu falei abrir painel"
    if not outro_painel and (tem(n_painel, "painel do ghost", "seu painel", "tela de indicadores", "seus indicadores",
                                 "indicadores do ghost", "abrir painel", "abrir o painel", "abre o painel", "abra o painel",
                                 "abre painel", "abra painel", "mostrar o painel", "mostra o painel", "fechar o painel",
                                 "fecha o painel", "fechar painel")
                             or (len(n_painel.split()) <= 4 and tem(n_painel, "painel", "indicadores"))):
        from ghost.nucleo import painel
        if re.search(r"\b(escond\w*|ocult\w*|deslig\w*|fech\w*)\b", n):
            painel.fechar_janela(); falar("Painel fechado, senhor."); return True
        if re.search(r"\b(mostr\w*|exib\w*|abr\w*|abra|volt\w*|ver|veja)\b", n):
            falar("Abrindo o painel, senhor." if painel.abrir_janela() else "Senhor, o painel não está disponível agora.")
            return True
    return False

def _tratar_google(n, falar):
    if tem(n, "conectar minha conta google", "conectar a conta google", "conectar o google", "conectar meu gmail",
           "conectar minha agenda"):
        from ghost.servicos import google_conta
        falar("Vou abrir o navegador para o senhor autorizar o acesso de leitura.")
        em_segundo_plano(lambda: falar(google_conta.conectar()))
        return True
    return False

def _tratar_ativacao(n, falar):
    if tem(n, "treinar ativacao", "treinar a ativacao", "treinar palavra de ativacao", "treinar a palavra de ativacao",
           "aprender minha voz", "treinar meu chamado", "treinar o chamado"):
        from ghost.voz import palavra
        em_segundo_plano(palavra.treinar_interativo, falar)
        return True
    if tem(n, "esquecer treino da ativacao", "apagar treino da ativacao", "esquecer o treino da ativacao"):
        from ghost.voz import palavra
        palavra.esquecer()
        falar("Treino da ativação apagado, senhor. Voltei a usar o reconhecedor padrão.")
        return True
    if tem(n, "ativacao por voz", "palavra de ativacao", "ouvir meu chamado", "me ouvir sem o f9"):
        from ghost.voz import ativacao
        if re.search(VERBO_DESLIGAR, n):
            ativacao.ligar(False, falar); return True
        if re.search(VERBO_LIGAR, n):
            ativacao.ligar(True, falar); return True
    return False

def _tratar_ghost(n, falar):
    if _tratar_alertas(n, falar) or _tratar_personalidade(n, falar) or _tratar_hud(n, falar) or _tratar_google(n, falar) or _tratar_ativacao(n, falar) or _executar_acao_cadastrada(n, falar):
        return True
    if tem(n, "cadastro de gestos", "cadastro dos gestos", "cadastrar gesto", "cadastrar gestos",
           "cadastrar um gesto", "novo gesto", "outro monitor", "proximo monitor", "trocar de monitor",
           "trocar monitor", "os dois monitores", "um monitor por vez"):
        if not GESTOS_ATIVOS:
            falar(AVISO_GESTOS)
            return True
        from ghost.visao import gestos
        if tem(n, "cadastro de gestos", "cadastro dos gestos", "cadastrar gesto", "cadastrar gestos",
               "cadastrar um gesto", "novo gesto"):
            abrir_cadastro(falar)
        elif tem(n, "os dois monitores"):
            gestos.MODO_MONITORES = "todos"
            falar("Gestos cobrindo os dois monitores, senhor.")
        elif tem(n, "um monitor por vez"):
            gestos.MODO_MONITORES = "um_por_vez"
            falar("Gestos em um monitor por vez. Diga outro monitor para trocar, senhor.")
        else:
            gestos.trocar_monitor(falar)
        return True
    return False

# -------------------------------------------------------------
# PONTO DE ENTRADA
# -------------------------------------------------------------
# -------------------------------------------------------------
# CONFIRMAÇÃO POR VOZ ("sim" / "não") quando o Ghost fica em dúvida
# -------------------------------------------------------------
_confirmacao = None  # {"t", "funcao"}
TEMPO_CONFIRMACAO = 60
# Confirmação só com resposta CURTA e clara. Antes "pode abrir o Excel" confirmava a pergunta pendente
# (porque começava com "pode") e o comando de abrir o Excel era engolido.
SIM = {"sim", "confirmo", "confirma", "pode", "pode sim", "sim pode", "claro", "ok", "positivo", "isso",
       "sim senhor", "pode fazer", "pode mandar", "pode salvar", "sim por favor", "confirmado", "manda", "faz"}
NAO = {"nao", "cancela", "cancelar", "deixa", "deixa pra la", "esquece", "negativo", "nao precisa", "agora nao",
       "nao obrigado"}

def comando_sensivel(texto):
    """Descrição da ação se o comando mexe em algo importante (pedido pelo celular pede confirmação), senão None."""
    n = normalizar(texto)
    curta = re.sub(r"\b(ghost|senhor)\b", "", n).strip()
    if curta in SIM or curta in NAO or curta.startswith("nao "):
        return None                                 # resposta a uma confirmação
    m = REGEX_MENSAGEM.match(texto)
    if m:
        return f"mandar no WhatsApp para {m.group('contato').strip()}: {m.group('msg').strip()[:80]}"
    m = REGEX_DITADO.match(texto)
    if m:
        return f"digitar no computador: {m.group('t').strip()[:80]}"
    m = REGEX_TECLA.search(n)
    if m:
        return f"apertar {m.group('k')}"
    if re.fullmatch(r"(?:ghost )?(?:desliga|desligar|desligue) (?:o )?(?:computador|pc)(?: agora)?", n):
        return "desligar o computador"
    if tem(n, "fechar janela", "fecha a janela", "feche a janela"):
        return "fechar a janela aberta"
    m = REGEX_FECHAR_APP.match(n)
    if m:
        return f"fechar {m.group('nome')}"
    if REGEX_ESQUECER.search(n) or tem(n, "esqueca a skill", "apague a skill", "apagar a skill", "excluir a skill"):
        return "apagar um cadastro"
    from ghost.ia import skills
    s = skills.encontrar(n)
    if s:
        return f"rodar a skill {s['nome']}"
    return None


def pedir_confirmacao(pergunta, funcao, falar=None):
    global _confirmacao
    _confirmacao = {"t": time.time(), "funcao": funcao}
    if falar:
        falar(pergunta)

def _tratar_confirmacao(n, falar):
    global _confirmacao
    c, _confirmacao = _confirmacao, None
    if not c or time.time() - c["t"] > TEMPO_CONFIRMACAO or not n:
        return False
    curta = re.sub(r"\b(ghost|senhor)\b", "", n).strip()
    if curta in NAO or curta.startswith("nao "):
        falar("Cancelado, senhor.")
        return True
    if curta in SIM:
        em_segundo_plano(c["funcao"])
        return True
    return False  # falou outra coisa: descarta a pergunta e o comando segue normalmente

# -------------------------------------------------------------
# QUALQUER APLICATIVO INSTALADO (lista do Menu Iniciar)
# -------------------------------------------------------------
REGEX_ABRIR_APP = re.compile(
    r"^(?:(?:por favor|voce|vc|pode|consegue|poderia|me|ghost)\s+)*"
    r"(?:abr(?:a|e|ir)|inici(?:a|e|ar)|execut(?:a|e|ar)|carreg(?:a|ue|ar))\s+"     # não pega "abril", "início"
    r"(?:(?:o|a|os|as)\s+)?(?:(?:aplicativo|programa|app|sistema)\s+(?:do\s+|da\s+|de\s+)?)?"
    r"(?P<nome>.+?)(?:\s+(?:pra mim|para mim|por favor))?$")
REGEX_FECHAR_APP = re.compile(r"^(?:(?:por favor|ghost)\s+)*(?:fech(?:a|e|ar)|encerr(?:a|e|ar))\s+(?:o\s+|a\s+)?"
                              r"(?:(?:aplicativo|programa|app)\s+)?(?P<nome>.+)$")

def _tratar_apps(n, falar):
    from ghost.automacao import apps
    m = REGEX_FECHAR_APP.search(n)
    if m and m.group("nome") not in ("janela", "a janela") and len(m.group("nome")) >= 3:
        alvo = m.group("nome")
        qtd = apps.fechar(alvo)
        falar(f"{alvo.capitalize()} fechado, senhor." if qtd else f"Senhor, não encontrei {alvo} aberto.")
        return True
    m = REGEX_ABRIR_APP.search(n)
    if not m:
        return False
    alvo = m.group("nome").strip()
    app, conf = apps.encontrar(alvo)
    if app and conf >= apps.CONFIANCA_DIRETA:
        apps.abrir(app)
        falar(f"Abrindo {app['nome']}, senhor.")
        return True
    if app and conf >= apps.CONFIANCA_MINIMA:
        pedir_confirmacao(f"Senhor, não achei {alvo} exatamente. Quer que eu abra {app['nome']}?",
                          lambda: (apps.abrir(app), falar(f"Abrindo {app['nome']}, senhor.")), falar)
        return True
    return False

# -------------------------------------------------------------
# PONTO DE ENTRADA
# -------------------------------------------------------------
_pergunta = None    # {"evento", "resposta", "t"}: uma skill esperando uma resposta livre do senhor
CANCELAR = {"cancela", "cancelar", "pare", "parar", "esquece", "deixa", "deixa pra la", "nao"}


def perguntar(pergunta, falar, tempo=120):
    """Faz uma pergunta e ESPERA a próxima fala (voz, F9 ou celular). Devolve o texto ou None (cancelou/sem resposta)."""
    global _pergunta
    p = {"evento": threading.Event(), "resposta": None, "t": time.time()}
    _pergunta = p
    falar(pergunta)
    try:
        from ghost.voz import ativacao
        ativacao.aguardar_comando(20)             # pode responder sem dizer "Ghost"
    except Exception:
        pass
    p["evento"].wait(tempo)
    if _pergunta is p:
        _pergunta = None
    return p["resposta"]


def _tratar_pergunta(texto, n):
    global _pergunta
    p = _pergunta
    if not p or p["evento"].is_set():
        return False
    _pergunta = None
    curta = re.sub(r"\b(ghost|senhor)\b", "", n).strip()
    p["resposta"] = None if curta in CANCELAR else texto.strip()
    p["evento"].set()
    return True


def executar(texto, falar):
    """Tenta resolver o comando localmente. Retorna True se executou algo; False para mandar à IA."""
    n = normalizar(texto)
    return (
        _tratar_pergunta(texto, n)
        or _tratar_confirmacao(n, falar)
        or _tratar_demonstracao(texto, n, falar)
        or _tratar_skills(texto, n, falar)
        or _tratar_pessoas(texto, n, falar)
        or _tratar_resumo(texto, n, falar)
        or _tratar_ghost(n, falar)
        or _tratar_whatsapp(texto, n, falar)
        or _tratar_ditado_e_teclas(texto, n, falar)
        or _tratar_programas_e_sites(texto, n, falar)
        or _tratar_sistema(n, falar)
        or _tratar_apps(n, falar)
    )
