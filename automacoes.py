"""
GHOST - Automações locais (as "mãos" do assistente).

Todo comando falado passa primeiro por executar(). Se for uma ação local
(abrir programa, site, WhatsApp, volume...), ela é feita aqui, sem gastar
cota de IA, e a função retorna True. Se retornar False, o ghost.py manda
a pergunta para a IA.
"""
import os
import re
import sys
import time
import threading
import subprocess
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

import camera
import gestos
import rosto
from gestos import alternar_camera

PASTA_GHOST = os.path.dirname(os.path.abspath(__file__))
PASTA_PRINTS = os.path.join(PASTA_GHOST, "prints")

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

def em_segundo_plano(funcao, *args):
    threading.Thread(target=funcao, args=args, daemon=True).start()

def _colar(texto):
    if pyperclip:
        pyperclip.copy(texto)
        time.sleep(0.05)
        pyautogui.hotkey("ctrl", "v")
    else:
        pyautogui.write(texto, interval=0.01)  # sem pyperclip: acentos podem falhar

# -------------------------------------------------------------
# WHATSAPP
# -------------------------------------------------------------
# Quando você disser "para mim" / "para mim mesmo":
MEU_NUMERO = ""          # seu número com DDI+DDD, só dígitos (ex.: "5511999998888"). Se preenchido, é usado direto.
MEU_CONTATO = "Você"     # senão, texto pesquisado na busca do WhatsApp para achar a sua própria conversa

REGEX_MENSAGEM = re.compile(
    r"(?:mand\w*|envi\w*|escrev\w*)\s+"
    r"(?:uma\s+)?(?:mensagem\s+)?(?:(?:no|pelo)\s+whats\s?app\s+(?:web\s+)?)?"
    r"(?:para|pra|pro)\s+(?:o\s+|a\s+)?"
    r"(?P<contato>.+?)[\s,:.]+"
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
    r"^(?:(?:por\s+favor|voc[eê]|pode|ghost)[\s,]+)*(?:digit\w*|escrev\w*)[\s,:]+"
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
    if m:
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

    if tem(n, "camera", "gestos"):
        if re.search(r"\b(fech\w*|deslig\w*|desativ\w*|par\w*)\b", n):
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

    if tem(n, "tirar print", "tira um print", "capturar tela", "captura de tela"):
        os.makedirs(PASTA_PRINTS, exist_ok=True)
        arquivo = os.path.join(PASTA_PRINTS, f"print_{datetime.now():%Y%m%d_%H%M%S}.png")
        pyautogui.screenshot().save(arquivo)
        falar("Captura realizada, senhor.")
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
    if tem(n, "desligar computador", "desligar o computador", "desliga o computador"):
        falar("Desligando em 30 segundos. Diga cancelar desligamento para abortar, senhor.")
        os.system("shutdown /s /t 30")
        return True
    return False

# -------------------------------------------------------------
# GHOST: CADASTRO DE GESTOS, LEITURA FACIAL, CHECK-IN, MONITORES
# -------------------------------------------------------------
def abrir_cadastro(falar):
    """Libera a câmera, abre a tela de cadastro e devolve a câmera quando ela fechar."""
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pyw):
        pyw = sys.executable
    suspensos = camera.suspender_todos()
    proc = subprocess.Popen([pyw, os.path.join(PASTA_GHOST, "cadastro_gestos.py")], cwd=PASTA_GHOST)
    falar("Abrindo o cadastro de gestos, senhor.")
    def _esperar():
        proc.wait()
        camera.retomar_todos()
        if suspensos:
            print("\n[AUTOMAÇÃO]: cadastro fechado, câmera devolvida ao Ghost.")
    threading.Thread(target=_esperar, daemon=True).start()

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
    import gestos_lib as gl
    import macros
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

def _tratar_ghost(n, falar):
    if _executar_acao_cadastrada(n, falar):
        return True
    if tem(n, "cadastro de gestos", "cadastro dos gestos", "cadastrar gesto", "cadastrar gestos",
           "cadastrar um gesto", "novo gesto"):
        abrir_cadastro(falar)
        return True

    if tem(n, "leitura facial", "leitura do rosto", "leitura de expressao", "leitura da expressao",
           "reconhecimento facial", "leitura de rosto"):
        if re.search(VERBO_DESLIGAR, n):
            rosto.ativar_leitura(False, falar); return True
        if re.search(VERBO_LIGAR, n):
            rosto.ativar_leitura(True, falar); return True

    if tem(n, "nao me pergunte", "nao pergunte", "me deixe em paz", "sem perguntas"):
        rosto.adiar(_minutos_falados(n), falar)
        return True
    if tem(n, "check in", "checkin", "perguntar como estou", "perguntas de como estou"):
        if re.search(VERBO_DESLIGAR, n):
            rosto.ligar_checkin(False, falar); return True
        if re.search(VERBO_LIGAR, n):
            rosto.ligar_checkin(True, falar); return True
    if tem(n, "como eu estou", "como estou", "qual meu estado", "como esta minha expressao",
           "minha expressao") and len(n.split()) <= 7:
        falar(rosto.descrever_agora())
        return True

    if tem(n, "outro monitor", "proximo monitor", "trocar de monitor", "trocar monitor",
           "mudar de monitor", "monitor seguinte", "outra tela", "proxima tela"):
        gestos.trocar_monitor(falar)
        return True
    if tem(n, "os dois monitores", "ambos os monitores", "duas telas"):
        gestos.MODO_MONITORES = "todos"
        falar("Gestos cobrindo os dois monitores, senhor.")
        return True
    if tem(n, "um monitor por vez", "uma tela por vez", "um monitor de cada vez"):
        gestos.MODO_MONITORES = "um_por_vez"
        falar("Gestos em um monitor por vez. Diga outro monitor para trocar, senhor.")
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
SIM = ("sim", "pode", "confirmo", "confirma", "isso", "claro", "ok", "abre", "positivo")
NAO = ("nao", "cancela", "cancelar", "deixa", "esquece", "negativo")

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
    primeira = n.split()[0]
    if (n in SIM or primeira in SIM) and not tem(n, "nao"):
        em_segundo_plano(c["funcao"])
        return True
    if n in NAO or primeira in NAO:
        falar("Cancelado, senhor.")
        return True
    return False  # falou outra coisa: descarta a pergunta e segue normalmente

# -------------------------------------------------------------
# QUALQUER APLICATIVO INSTALADO (lista do Menu Iniciar)
# -------------------------------------------------------------
REGEX_ABRIR_APP = re.compile(
    r"^(?:(?:por favor|voce|vc|pode|consegue|poderia|me|ghost)\s+)*"
    r"(?:abr\w*|abra|inici\w*|execut\w*|carreg\w*)\s+"
    r"(?:(?:o|a|os|as)\s+)?(?:(?:aplicativo|programa|app|sistema)\s+(?:do\s+|da\s+|de\s+)?)?"
    r"(?P<nome>.+?)(?:\s+(?:pra mim|para mim|por favor))?$")
REGEX_FECHAR_APP = re.compile(r"^(?:(?:por favor|ghost)\s+)*(?:fech\w*|encerr\w*)\s+(?:o\s+|a\s+)?"
                              r"(?:(?:aplicativo|programa|app)\s+)?(?P<nome>.+)$")

def _tratar_apps(n, falar):
    import apps
    m = REGEX_FECHAR_APP.search(n)
    if m and m.group("nome") not in ("janela", "a janela"):
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
def executar(texto, falar):
    """Tenta resolver o comando localmente. Retorna True se executou algo; False para mandar à IA."""
    n = normalizar(texto)
    return (
        _tratar_confirmacao(n, falar)
        or _tratar_ghost(n, falar)
        or _tratar_whatsapp(texto, n, falar)
        or _tratar_ditado_e_teclas(texto, n, falar)
        or _tratar_programas_e_sites(texto, n, falar)
        or _tratar_sistema(n, falar)
        or _tratar_apps(n, falar)
    )
