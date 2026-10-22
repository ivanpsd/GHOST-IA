"""
GHOST - Ferramentas que a IA pode usar para AGIR no computador.

A IA não "diz que não consegue": quando o pedido é uma ação coberta por estas
ferramentas, ela chama a ferramenta e o Ghost executa. O conjunto é FECHADO:
não existe execução de comando livre. Consultas do sistema são só leitura.
"""
import re
import json
import subprocess
import webbrowser
from urllib.parse import quote_plus

import pyautogui

import apps

TOOLS = [
    {"type": "function", "function": {
        "name": "abrir_aplicativo",
        "description": "Abre qualquer aplicativo/programa instalado no Windows pelo nome (ex.: Excel, AnyDesk, Spotify, Protheus).",
        "parameters": {"type": "object", "properties": {"nome": {"type": "string"}}, "required": ["nome"]}}},
    {"type": "function", "function": {
        "name": "fechar_aplicativo",
        "description": "Fecha as janelas de um aplicativo pelo nome.",
        "parameters": {"type": "object", "properties": {"nome": {"type": "string"}}, "required": ["nome"]}}},
    {"type": "function", "function": {
        "name": "abrir_site",
        "description": "Abre um endereço da web no navegador.",
        "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "pesquisar_web",
        "description": "Abre uma pesquisa no Google ou YouTube. Use para notícias, cotações, clima e qualquer informação atual.",
        "parameters": {"type": "object", "properties": {
            "termo": {"type": "string"}, "site": {"type": "string", "enum": ["google", "youtube"]}},
            "required": ["termo"]}}},
    {"type": "function", "function": {
        "name": "digitar_texto",
        "description": "Digita um texto na janela que está em foco.",
        "parameters": {"type": "object", "properties": {"texto": {"type": "string"}}, "required": ["texto"]}}},
    {"type": "function", "function": {
        "name": "pressionar_teclas",
        "description": "Pressiona uma tecla ou atalho, ex.: 'enter', 'ctrl+c', 'win+d', 'alt+f4'.",
        "parameters": {"type": "object", "properties": {"combo": {"type": "string"}}, "required": ["combo"]}}},
    {"type": "function", "function": {
        "name": "comando_ghost",
        "description": ("Executa um comando local do Ghost escrito como o usuário falaria. Use para: enviar mensagem "
                        "no WhatsApp ('mande mensagem para X dizendo Y'), volume, mídia, print de tela, gestos, "
                        "leitura facial, check-in, monitores, executar ação/macro cadastrada."),
        "parameters": {"type": "object", "properties": {"frase": {"type": "string"}}, "required": ["frase"]}}},
    {"type": "function", "function": {
        "name": "consultar_sistema",
        "description": "Consulta informações do computador (somente leitura).",
        "parameters": {"type": "object", "properties": {"item": {"type": "string", "enum": [
            "espaco_em_disco", "memoria", "endereco_ip", "programas_abertos", "data_e_hora", "bateria", "uso_de_cpu"]}},
            "required": ["item"]}}},
]

# Consultas fixas, somente leitura (nenhum comando livre é executado)
CONSULTAS = {
    "espaco_em_disco": "Get-PSDrive -PSProvider FileSystem | Select-Object Name,@{n='LivreGB';e={[math]::Round($_.Free/1GB,1)}},@{n='UsadoGB';e={[math]::Round($_.Used/1GB,1)}} | Format-Table -AutoSize | Out-String",
    "memoria": "$o=Get-CimInstance Win32_OperatingSystem; 'Total GB: '+[math]::Round($o.TotalVisibleMemorySize/1MB,1)+' | Livre GB: '+[math]::Round($o.FreePhysicalMemory/1MB,1)",
    "endereco_ip": "Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.IPAddress -notlike '127.*'} | Select-Object InterfaceAlias,IPAddress | Format-Table -AutoSize | Out-String",
    "programas_abertos": "Get-Process | Where-Object {$_.MainWindowTitle} | Select-Object ProcessName,MainWindowTitle | Format-Table -AutoSize | Out-String -Width 150",
    "data_e_hora": "Get-Date -Format 'dddd, dd/MM/yyyy HH:mm'",
    "bateria": "$b=Get-CimInstance Win32_Battery; if($b){'Carga: '+$b.EstimatedChargeRemaining+'%'}else{'Sem bateria (desktop)'}",
    "uso_de_cpu": "'CPU: '+[math]::Round((Get-CimInstance Win32_Processor | Measure-Object LoadPercentage -Average).Average,0)+'%'",
}
LIMITE_SAIDA = 3000


def _consulta(item):
    comando = CONSULTAS[item]
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + comando],
                       capture_output=True, timeout=30, creationflags=0x08000000)
    saida = (r.stdout + r.stderr).decode("utf-8", errors="replace").strip()
    return saida[:LIMITE_SAIDA] or "(sem saída)"


def executar(nome, args, falar, pedir_confirmacao):
    """Executa uma ferramenta.
    Retorna (resultado_para_ia, precisa_resposta_da_ia).
    - Ações simples: o Ghost confirma por voz e a IA não precisa responder de novo.
    - Consultas do sistema: a saída volta para a IA explicar.
    """
    try:
        if nome == "abrir_aplicativo":
            app, conf = apps.encontrar(args.get("nome", ""))
            if app and conf >= apps.CONFIANCA_MINIMA:
                apps.abrir(app)
                falar(f"Abrindo {app['nome']}, senhor.")
                return f"aberto: {app['nome']}", False
            falar(f"Senhor, não encontrei o aplicativo {args.get('nome')} instalado.")
            return "não encontrado", False

        if nome == "fechar_aplicativo":
            n = apps.fechar(args.get("nome", ""))
            falar(f"Fechei {n} janela{'s' if n != 1 else ''}, senhor." if n else
                  f"Senhor, não encontrei janela de {args.get('nome')} aberta.")
            return f"{n} janelas fechadas", False

        if nome == "abrir_site":
            url = args.get("url", "")
            if not re.match(r"^https?://", url):
                url = "https://" + url
            webbrowser.open(url)
            falar("Abrindo o site, senhor.")
            return "aberto", False

        if nome == "pesquisar_web":
            termo, site = args.get("termo", ""), args.get("site", "google")
            webbrowser.open(f"https://www.youtube.com/results?search_query={quote_plus(termo)}" if site == "youtube"
                            else f"https://www.google.com/search?q={quote_plus(termo)}")
            falar(f"Pesquisando {termo}, senhor.")
            return "pesquisa aberta", False

        if nome == "digitar_texto":
            import automacoes
            automacoes._colar(args.get("texto", ""))
            return "digitado", False

        if nome == "pressionar_teclas":
            pyautogui.hotkey(*[t.strip().lower() for t in args.get("combo", "").split("+") if t.strip()])
            return "pressionado", False

        if nome == "comando_ghost":
            import automacoes
            ok = automacoes.executar(args.get("frase", ""), falar)
            if not ok:
                falar("Senhor, esse comando não existe nas minhas automações.")
            return "executado" if ok else "comando não reconhecido", False

        if nome == "consultar_sistema":
            item = args.get("item", "")
            if item not in CONSULTAS:
                return "consulta não disponível", False
            return _consulta(item), True

        return f"ferramenta desconhecida: {nome}", False
    except Exception as e:
        print(f"\n[FERRAMENTA]: erro em {nome}: {e!r}")
        falar("Senhor, houve uma falha ao executar a ação.")
        return f"erro: {e}", False


def args_json(texto):
    try:
        return json.loads(texto or "{}")
    except Exception:
        return {}
