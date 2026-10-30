"""
GHOST - Ferramentas que a IA pode usar para AGIR no computador.

A IA não "diz que não consegue": quando o pedido é uma ação coberta por estas
ferramentas, ela chama a ferramenta e o Ghost executa. O conjunto é FECHADO:
não existe execução de comando livre. Consultas do sistema são só leitura.
"""
import json
import re
import subprocess
import webbrowser
from urllib.parse import quote_plus

import pyautogui

from ghost.automacao import apps

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
                        "no WhatsApp ('mande mensagem para X dizendo Y'), volume, mídia, print de tela, painel, celular e "
                        "skills pela tela ('aprenda uma skill pela tela', 'parar de gravar', 'teste a skill', "
                        "'salve a skill como X', 'mostre a revisão') e as TELAS do Ghost: 'abrir planta das câmeras' "
                        "(câmeras da empresa em 3D, painel/modelo/HUD das câmeras) e 'abrir link neural' (mapa da rede). "
                        "Telas não são arquivos nem aplicativos: nunca pergunte caminho, use este comando."),
        "parameters": {"type": "object", "properties": {"frase": {"type": "string"}}, "required": ["frase"]}}},
    {"type": "function", "function": {
        "name": "ver_planilha",
        "description": ("Mostra a estrutura de uma planilha Excel/CSV do usuário (abas, colunas, 3 linhas de exemplo). "
                        "Use ANTES de calcular_planilha. 'nome' é como o usuário chama o arquivo."),
        "parameters": {"type": "object", "properties": {"nome": {"type": "string"}, "aba": {"type": "string"}},
                       "required": ["nome"]}}},
    {"type": "function", "function": {
        "name": "calcular_planilha",
        "description": ("Calcula sobre uma planilha (somente leitura): filtra linhas, agrupa e soma/média/contagem/max/min. "
                        "Datas em AAAA-MM-DD (use o horário AGORA para 'ontem', 'este mês'). Use os nomes de coluna vistos em ver_planilha. "
                        "Para 'qual produto/cliente/turno teve mais...', use agrupar_por com operacao soma e ordenar desc."),
        "parameters": {"type": "object", "properties": {
            "nome": {"type": "string"}, "aba": {"type": "string"},
            "filtros": {"type": "array", "items": {"type": "object", "properties": {
                "coluna": {"type": "string"},
                "operador": {"type": "string", "enum": ["=", "!=", "contem", ">", ">=", "<", "<=", "entre"]},
                "valor": {"type": "string", "description": "para 'entre': 'inicio|fim'"}}, "required": ["coluna", "operador", "valor"]}},
            "agrupar_por": {"type": "string"},
            "coluna_valor": {"type": "string"},
            "operacao": {"type": "string", "enum": ["soma", "media", "contagem", "max", "min"]},
            "ordenar": {"type": "string", "enum": ["desc", "asc"]},
            "limite": {"type": "integer"}}, "required": ["nome"]}}},
    {"type": "function", "function": {
        "name": "previsao_do_tempo",
        "description": "Clima de hoje (agora, mínima, máxima, chance de chuva). Sem cidade, usa a cidade do usuário.",
        "parameters": {"type": "object", "properties": {"cidade": {"type": "string"}}, "required": []}}},
    {"type": "function", "function": {
        "name": "resumo_do_dia",
        "description": "Resumo do dia: data, clima, lembretes de hoje e agenda/e-mails se conectados.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "consultar_agenda",
        "description": "Lê os compromissos das agendas do usuário (trabalho e pessoais), somente leitura.",
        "parameters": {"type": "object", "properties": {
            "periodo": {"type": "string", "description": "'hoje', 'amanha', 'semana' ou uma data AAAA-MM-DD"},
            "conta": {"type": "string", "description": "opcional: 'pessoal', 'trabalho' ou o nome da conta"}},
            "required": ["periodo"]}}},
    {"type": "function", "function": {
        "name": "consultar_emails",
        "description": "Lê remetente e assunto dos e-mails da caixa de entrada (trabalho e pessoais), somente leitura.",
        "parameters": {"type": "object", "properties": {
            "apenas_nao_lidos": {"type": "boolean"},
            "remetente": {"type": "string", "description": "quem enviou, do jeito que o usuário falou (ex.: 'Deborah', 'minha líder'); o Ghost resolve pelas fichas"},
            "quantidade": {"type": "integer"},
            "conta": {"type": "string", "description": "opcional: 'pessoal', 'trabalho' ou o nome da conta"}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "criar_lembrete",
        "description": ("Cria um lembrete/alarme. Converta o horário falado ('às 15h', 'daqui a 20 minutos', "
                        "'amanhã às 9') para data e hora absolutas usando o horário AGORA informado."),
        "parameters": {"type": "object", "properties": {
            "quando": {"type": "string", "description": "AAAA-MM-DD HH:MM"},
            "texto": {"type": "string", "description": "do que lembrar, curto"}}, "required": ["quando", "texto"]}}},
    {"type": "function", "function": {
        "name": "listar_lembretes", "description": "Lista os lembretes marcados.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "cancelar_lembrete", "description": "Cancela lembretes que contenham o trecho informado.",
        "parameters": {"type": "object", "properties": {"trecho": {"type": "string"}}, "required": ["trecho"]}}},
    {"type": "function", "function": {
        "name": "olhar_camera",
        "description": ("Tira uma foto pela webcam e descreve o que aparece. Use SEMPRE que o usuário pedir para "
                        "você ver, olhar ou identificar algo ('o que é isso?', 'o que tem na minha mão?', "
                        "'olha isso', 'o que você está vendo?'). Nunca peça para ele descrever o objeto."),
        "parameters": {"type": "object", "properties": {"pergunta": {"type": "string"}}, "required": ["pergunta"]}}},
    {"type": "function", "function": {
        "name": "criar_skill",
        "description": ("Cria uma skill: uma sequência de ações no PC (abrir programas/sites, digitar, teclas, "
                        "mensagens) disparada por uma frase. NÃO use para mudar o jeito de o Ghost falar "
                        "ou cumprimentar (para isso use definir_saudacao)."),
        "parameters": {"type": "object", "properties": {"descricao": {"type": "string",
            "description": "a descrição completa do usuário: nome, frase de disparo e passos"}},
            "required": ["descricao"]}}},
    {"type": "function", "function": {
        "name": "definir_saudacao",
        "description": ("Muda a frase que o Ghost fala ao ser chamado (ao iniciar e ao ser acionado pelo F9 depois "
                        "de um tempo parado). Use quando o usuário pedir para o Ghost cumprimentá-lo de outro jeito."),
        "parameters": {"type": "object", "properties": {"frase": {"type": "string"}}, "required": ["frase"]}}},
    {"type": "function", "function": {
        "name": "consultar_sistema",
        "description": "Consulta informações do computador (somente leitura).",
        "parameters": {"type": "object", "properties": {"item": {"type": "string", "enum": [
            "espaco_em_disco", "memoria", "endereco_ip", "programas_abertos", "data_e_hora", "bateria", "uso_de_cpu"]}},
            "required": ["item"]}}},
    {"type": "function", "function": {
        "name": "consultar_rede",
        "description": ("Rede da empresa, SOMENTE LEITURA: aparelhos ligados (listar), procurar uma máquina (por "
                        "apelido, responsável, departamento, nome, IP), aparelhos novos nas últimas 24 h, internet agora, "
                        "historico_internet (disponibilidade, latência e quedas no período), quedas (aparelhos críticos "
                        "que caíram e voltaram, 7 dias), exportar (Excel com inventário, quedas e internet por dia), impressoras "
                        "(toner, papel e erros). Ligar, desligar, reiniciar ou mandar mensagem NÃO é por aqui: o senhor "
                        "faz manualmente pelos botões do link neural. "
                        "Nunca liga, desliga ou altera máquinas."),
        "parameters": {"type": "object", "properties": {
            "acao": {"type": "string", "enum": ["listar", "procurar", "novos", "internet", "historico_internet",
                                                 "quedas", "exportar", "impressoras"]},
            "periodo": {"type": "string", "enum": ["hoje", "24h", "semana", "mes"],
                        "description": "só para historico_internet"},
            "termo": {"type": "string", "description": "o que procurar (só para acao=procurar)"}},
            "required": ["acao"]}}},
    {"type": "function", "function": {
        "name": "consultar_maquinas",
        "description": ("Máquinas com agente MeshCentral (SOMENTE LEITURA): quem está logado, se está ligada e desde "
                        "quando, sistema, antivírus, firewall, atualizações, reinício pendente. acao: listar (todas), "
                        "procurar (por nome, IP, usuário, apelido ou responsável), alertas (só as com problema). Use para "
                        "'quem está logado no PC do X', 'alguma máquina sem antivírus'. Não controla as máquinas."),
        "parameters": {"type": "object", "properties": {
            "acao": {"type": "string", "enum": ["listar", "procurar", "alertas"]},
            "termo": {"type": "string"}}, "required": ["acao"]}}},
    {"type": "function", "function": {
        "name": "departamentos_rede",
        "description": ("Departamentos do mapa da rede (link neural), só no inventário do Ghost. acao: criar (lista de "
                        "nomes), remover, listar, atribuir (coloca os aparelhos 'alvos' — IPs ou nomes — no departamento "
                        "'departamento'). Use quando pedirem para criar departamentos ou pôr máquinas num setor."),
        "parameters": {"type": "object", "properties": {
            "acao": {"type": "string", "enum": ["criar", "remover", "listar", "atribuir"]},
            "nomes": {"type": "array", "items": {"type": "string"}},
            "departamento": {"type": "string"},
            "alvos": {"type": "array", "items": {"type": "string"}}}, "required": ["acao"]}}},
    {"type": "function", "function": {
        "name": "ensinar_comando",
        "description": ("Grava que uma FRASE do usuário deve fazer o mesmo que um comando que já existe (ex.: frase "
                        "'painel das câmeras' -> comando 'abrir planta das câmeras'). Use quando ele ensinar ou corrigir "
                        "um comando ('quando eu falar X faça Y', 'X é a mesma coisa que Y', 'eu já te ensinei isso'). "
                        "'comando' tem que ser uma frase que o comando_ghost já entende."),
        "parameters": {"type": "object", "properties": {"frase": {"type": "string"}, "comando": {"type": "string"}},
                       "required": ["frase", "comando"]}}},
    {"type": "function", "function": {
        "name": "nomear_maquina",
        "description": ("Anota no inventário do Ghost UM aparelho da rede: apelido, responsável, departamento. "
                        "'critico' SÓ quando o usuário pedir explicitamente para vigiar/marcar como crítico. 'alvo' = IP "
                        "(ex.: '192.168.50.13'; 'final 50.13' = esse IP), MAC ou nome atual. Não altera a máquina."),
        "parameters": {"type": "object", "properties": {
            "alvo": {"type": "string"}, "apelido": {"type": "string"}, "responsavel": {"type": "string"},
            "departamento": {"type": "string"}, "critico": {"type": "boolean"}}, "required": ["alvo"]}}},
    {"type": "function", "function": {
        "name": "olhar_tela",
        "description": ("Captura a tela do usuário NESTE momento e analisa. Use quando ele pedir para você ver/ler/"
                        "explicar algo na tela: 'o que é esse erro?', 'resume esse documento aberto', 'o que diz aqui?'. "
                        "alvo='janela' (padrão, janela ativa) ou 'tudo' (todos os monitores)."),
        "parameters": {"type": "object", "properties": {
            "pergunta": {"type": "string"}, "alvo": {"type": "string", "enum": ["janela", "tudo"]}},
            "required": ["pergunta"]}}},
    {"type": "function", "function": {
        "name": "buscar_memoria",
        "description": ("Busca nas conversas ANTIGAS com o usuário (todas, com data), pelo sentido. Use quando ele "
                        "perguntar o que disse/combinou/pediu antes ('o que eu te falei semana passada sobre X?', "
                        "'quando foi que falamos de Y?'). Datas no formato AAAA-MM-DD (opcionais)."),
        "parameters": {"type": "object", "properties": {
            "pergunta": {"type": "string"}, "data_inicio": {"type": "string"}, "data_fim": {"type": "string"}},
            "required": ["pergunta"]}}},
    {"type": "function", "function": {
        "name": "listar_notificacoes",
        "description": "Lista as últimas notificações do Windows recebidas (WhatsApp, Outlook, Teams...), com o texto.",
        "parameters": {"type": "object", "properties": {
            "quantidade": {"type": "integer"}, "app": {"type": "string"}}}}},
    {"type": "function", "function": {
        "name": "configurar_notificacoes",
        "description": ("Liga/desliga os avisos de notificações por voz, silencia por X minutos, ou escolhe se o "
                        "texto da mensagem é lido em voz alta."),
        "parameters": {"type": "object", "properties": {
            "acao": {"type": "string", "enum": ["ligar", "desligar", "silenciar", "ler_texto", "nao_ler_texto"]},
            "minutos": {"type": "integer"}}, "required": ["acao"]}}},
    {"type": "function", "function": {
        "name": "tarefa_segundo_plano",
        "description": ("Inicia uma tarefa LONGA de análise em segundo plano (comparar planilhas, resumir vários "
                        "e-mails, levantar números) e avisa quando terminar. Use quando o pedido exigir vários passos "
                        "ou o usuário disser 'me avisa quando terminar'. Só lê dados; não age no PC."),
        "parameters": {"type": "object", "properties": {"descricao": {"type": "string",
            "description": "o pedido completo do usuário, com todos os detalhes"}}, "required": ["descricao"]}}},
    {"type": "function", "function": {
        "name": "listar_tarefas", "description": "Mostra as tarefas em segundo plano e o andamento.",
        "parameters": {"type": "object", "properties": {}}}},
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


# Ferramentas que trazem texto escrito por OUTRAS pessoas / de fora do Ghost
EXTERNAS = {"consultar_emails", "consultar_agenda", "ver_planilha", "calcular_planilha", "olhar_camera",
            "olhar_tela", "listar_notificacoes", "buscar_memoria", "listar_tarefas",
            "consultar_sistema", "resumo_do_dia", "consultar_rede", "consultar_maquinas"}   # nomes de máquinas vêm de fora
# Ferramentas que AGEM (depois de ler algo externo, só com confirmação por voz)
ACOES = {"abrir_aplicativo", "fechar_aplicativo", "abrir_site", "pesquisar_web", "digitar_texto",
         "pressionar_teclas", "comando_ghost", "criar_skill", "definir_saudacao",
         "criar_lembrete", "cancelar_lembrete", "configurar_notificacoes", "tarefa_segundo_plano"}
# nomear_maquina / departamentos_rede ficam FORA de ACOES: só mudam rótulos no inventário do Ghost (nada na máquina),
# então não pedem "confirma?" a cada apelido.


# Ferramentas enviadas em TODO pedido; as outras só quando a frase combina (economiza tokens do plano gratuito)
SEMPRE = {"abrir_aplicativo", "fechar_aplicativo", "abrir_site", "pesquisar_web", "digitar_texto", "pressionar_teclas",
          "comando_ghost", "consultar_sistema", "olhar_tela", "buscar_memoria"}
GRUPOS = [
    (r"planilh|excel|csv|xlsx|tabela|coluna|soma|total|quant[oa]s?|media|produ[cz]|vend|estoque|calcul",
     {"ver_planilha", "calcular_planilha"}),
    (r"tempo|clima|chov|chuv|temperatura|frio|calor|sol\b|guarda.chuva", {"previsao_do_tempo"}),
    (r"resumo|meu dia|bom dia|hoje", {"resumo_do_dia"}),
    (r"agenda|reuni|compromisso|evento|calendario|e.?mail|caixa de entrada|inbox", {"consultar_agenda", "consultar_emails"}),
    (r"lembr|alarme|despert|me (cham|avis)|avise|daqui a|as \d", {"criar_lembrete", "listar_lembretes", "cancelar_lembrete"}),
    (r"camera|webcam|olha isso|ve isso|o que (e|eh) isso|na minha mao|segurando|mostrando|estou vestindo",
     {"olhar_camera"}),
    (r"skill|habilidade|automatiz|rotina", {"criar_skill"}),
    (r"quando eu (fal|dis|ped)|sempre que|ensin|aprend|mesma coisa|ja te (falei|disse|ensinei)|burro|comando",
     {"ensinar_comando"}),
    (r"sauda|cumpriment|me chame|me chama", {"definir_saudacao"}),
    (r"notifica|whats|mensage|quem (me )?(mandou|escreveu)", {"listar_notificacoes", "configurar_notificacoes"}),
    (r"\brede\b|maquina|computador|\bpcs?\b|\bips?\b|online|ligad|servidor|internet|wi.?fi|roteador|aparelho|"
     r"impressora|conexao|lento|ping|caiu|queda|critic|inventario|camera|logad|antivirus|firewall|reinici|"
     r"atualizac|agente|meshcentral|ligada desde|departamento|setor|link neural|renome|apelid",
     {"consultar_rede", "nomear_maquina", "consultar_maquinas", "departamentos_rede"}),
    (r"segundo plano|tarefa|enquanto|monitor|acompanh|fique de olho|verifique a cada", {"tarefa_segundo_plano",
                                                                                       "listar_tarefas"}),
]


def escolher(texto, anterior=""):
    """Ferramentas para este pedido: as de SEMPRE + os grupos que a frase (ou a anterior, para 'e o de ontem?')
    pede. Frase curta e vaga demais: manda todas."""
    import re
    import unicodedata
    t = unicodedata.normalize("NFD", f"{texto} {anterior}".lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    nomes = set(SEMPRE)
    for padrao, grupo in GRUPOS:
        if re.search(padrao, t):
            nomes |= grupo
    if len(texto.split()) <= 2 and nomes == SEMPRE and not anterior:
        return TOOLS
    return [x for x in TOOLS if x["function"]["name"] in nomes]


def descrever(nome, args):
    """Frase curta do que a ação vai fazer (para a pergunta de confirmação)."""
    v = lambda k: str(args.get(k, ""))[:60]
    return {"abrir_aplicativo": f"abrir {v('nome')}", "fechar_aplicativo": f"fechar {v('nome')}",
            "abrir_site": f"abrir o site {v('url')}", "pesquisar_web": f"pesquisar {v('termo')}",
            "digitar_texto": f"digitar: {v('texto')}", "pressionar_teclas": f"apertar {v('combo')}",
            "comando_ghost": f"executar: {v('frase')}",
            "criar_skill": "criar uma skill nova", "definir_saudacao": "mudar a saudação",
            "criar_lembrete": f"criar o lembrete {v('texto')}", "cancelar_lembrete": f"cancelar o lembrete {v('trecho')}",
            "nomear_maquina": f"anotar {v('alvo')} como {v('apelido') or v('departamento')}",
            }.get(nome, nome.replace("_", " "))


def precisa_confirmar(nome, args):
    """Ações no PC depois de ler conteúdo de fora pedem 'confirma?'. Telas do Ghost (catálogo 'seguro') não."""
    if nome not in ACOES:
        return False
    if nome in ("comando_ghost", "abrir_aplicativo"):
        from ghost.automacao import automacoes
        achado = automacoes.resolver_catalogo(args.get("frase") or args.get("nome") or "", aproximado=nome == "comando_ghost")
        if achado and achado[1]:
            return False
    return True


def executar(nome, args, falar, pedir_confirmacao):
    """Executa uma ferramenta.
    Retorna (resultado_para_ia, precisa_resposta_da_ia).
    - Ações simples: o Ghost confirma por voz e a IA não precisa responder de novo.
    - Consultas do sistema: a saída volta para a IA explicar.
    """
    try:
        if nome == "abrir_aplicativo":
            from ghost.automacao import automacoes
            achado = automacoes.resolver_catalogo(args.get("nome", ""), aproximado=False)
            if achado and achado[1]:                     # "Painel das Câmeras" não é programa: é tela do Ghost
                print(f"\n[CATÁLOGO]: abrir_aplicativo '{args.get('nome')}' -> '{achado[0]}'")
                if automacoes.executar(achado[0], falar):
                    return f"aberto: {achado[0]}", False
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
            from ghost.automacao import automacoes
            automacoes._colar(args.get("texto", ""))
            return "digitado", False

        if nome == "pressionar_teclas":
            pyautogui.hotkey(*[t.strip().lower() for t in args.get("combo", "").split("+") if t.strip()])
            return "pressionado", False

        if nome == "comando_ghost":
            from ghost.automacao import automacoes
            frase = args.get("frase", "")
            ok = automacoes.executar(frase, falar)
            if not ok:                                   # a IA escreveu do jeito dela: tenta o catálogo
                achado = automacoes.resolver_catalogo(frase)
                if achado and "<" not in achado[0]:
                    print(f"\n[CATÁLOGO]: '{frase}' -> '{achado[0]}'")
                    ok = automacoes.executar(achado[0], falar)
            if not ok:
                falar("Senhor, esse comando não existe nas minhas automações.")
            return "executado" if ok else "comando não reconhecido", False

        if nome in ("ver_planilha", "calcular_planilha"):
            from ghost.automacao import planilhas
            try:
                if nome == "ver_planilha":
                    return planilhas.estrutura(args.get("nome", ""), args.get("aba") or None), True
                return planilhas.calcular(args.get("nome", ""), args.get("aba") or None, args.get("filtros"),
                                          args.get("agrupar_por") or None, args.get("coluna_valor") or None,
                                          args.get("operacao", "soma"), args.get("ordenar", "desc"),
                                          args.get("limite", 10)), True
            except Exception as e:
                return f"erro ao ler a planilha: {e}", True

        if nome in ("previsao_do_tempo", "resumo_do_dia"):
            from ghost.servicos import resumo
            frase = resumo.clima(args.get("cidade") or None) if nome == "previsao_do_tempo" else resumo.gerar()
            falar(frase)
            return frase, False

        if nome in ("consultar_agenda", "consultar_emails"):
            from ghost.servicos import contas_pessoais, google_conta
            conta = (args.get("conta") or "").lower()
            usar_trabalho = google_conta.configurado() and conta in ("", "trabalho", "empresa", "google")
            usar_pessoal = contas_pessoais.configurado() and conta not in ("trabalho", "empresa", "google")
            if not (usar_trabalho or usar_pessoal):
                falar("Senhor, nenhuma conta de agenda ou e-mail está conectada ainda.")
                return "nenhuma conta conectada", False
            partes = []

            def juntar(rotulo, consulta, *a):        # uma conta fora do ar não apaga a resposta da outra
                try:
                    partes.append(rotulo + consulta(*a))
                except Exception as e:
                    partes.append(f"{rotulo}indisponível ({e})")

            conta_pessoal = "" if conta in ("", "pessoal") else conta
            if nome == "consultar_agenda":
                if usar_trabalho:
                    juntar("[trabalho] ", google_conta.agenda, args.get("periodo", "hoje"))
                if usar_pessoal:
                    juntar("", contas_pessoais.agenda, args.get("periodo", "hoje"), conta_pessoal)
            else:
                remetente = args.get("remetente", "") or ""
                if remetente:
                    from ghost.ia import pessoas
                    remetente = pessoas.resolver_contato(remetente)  # "minha líder" -> "Deborah"
                nao_lidos, qtd = args.get("apenas_nao_lidos", True), args.get("quantidade", 8)
                if usar_trabalho:
                    juntar("[trabalho] ", google_conta.emails, nao_lidos, remetente, qtd)
                if usar_pessoal:
                    juntar("", contas_pessoais.emails, nao_lidos, remetente, qtd, conta_pessoal)
            return "\n".join(partes), True

        if nome in ("criar_lembrete", "listar_lembretes", "cancelar_lembrete"):
            from ghost.servicos import lembretes
            if nome == "criar_lembrete":
                frase = lembretes.criar(args.get("quando", ""), args.get("texto", ""))
            elif nome == "listar_lembretes":
                frase = lembretes.listar()
            else:
                frase = lembretes.cancelar(args.get("trecho", ""))
            falar(frase)
            return frase, False

        if nome == "olhar_camera":
            from ghost.visao import visao
            falar("Deixe-me ver.")
            resposta = visao.olhar(args.get("pergunta", "o que é isso?"))
            falar(resposta)
            return f"visto pela câmera: {resposta}", False

        if nome == "criar_skill":
            from ghost.automacao import automacoes
            automacoes._montar_skill(args.get("descricao", ""), falar)
            return "montando a skill; o usuário vai confirmar por voz", False

        if nome == "definir_saudacao":
            from ghost.nucleo import preferencias
            frase = args.get("frase", "").strip()
            preferencias.definir("saudacao", frase)
            falar(f"Combinado. A partir de agora vou dizer: {frase}")
            return "saudação alterada", False

        if nome == "olhar_tela":
            from ghost.visao import tela
            falar("Deixe-me ver a tela.")
            resposta = tela.olhar(args.get("pergunta", "o que tem na tela?"), args.get("alvo", "janela"))
            return f"visto na tela: {resposta}", True

        if nome == "buscar_memoria":
            from ghost.ia import memoria_longa
            return memoria_longa.buscar(args.get("pergunta", ""), args.get("data_inicio", ""),
                                        args.get("data_fim", "")), True

        if nome == "listar_notificacoes":
            from ghost.servicos import notificacoes
            return notificacoes.listar(args.get("quantidade") or 5, args.get("app", "")), True

        if nome == "configurar_notificacoes":
            from ghost.nucleo import preferencias
            from ghost.servicos import notificacoes
            acao, minutos = args.get("acao"), int(args.get("minutos") or 60)
            if acao in ("ligar", "desligar"):
                preferencias.definir("notificacoes_ativas", acao == "ligar")
                frase = f"Avisos de notificações {'ligados' if acao == 'ligar' else 'desligados'}, senhor."
            elif acao == "silenciar":
                notificacoes.silenciar(minutos)
                frase = f"Notificações em silêncio por {minutos} minutos, senhor."
            else:
                preferencias.definir("notificacoes_ler_texto", acao == "ler_texto")
                frase = ("Vou ler o texto das notificações, senhor." if acao == "ler_texto"
                         else "Vou dizer só o aplicativo e quem mandou, senhor.")
            falar(frase)
            return frase, False

        if nome == "tarefa_segundo_plano":
            from ghost.ia import tarefas
            r = tarefas.criar(args.get("descricao", ""))
            falar("Pode deixar, senhor. Vou trabalhar nisso em segundo plano e aviso quando terminar.")
            return r, False

        if nome == "listar_tarefas":
            from ghost.ia import tarefas
            return tarefas.listar(), True

        if nome == "consultar_rede":
            from ghost.servicos import rede
            acao = args.get("acao", "listar")
            if acao == "historico_internet":
                return rede.texto_internet(args.get("periodo", "hoje")), True
            if acao == "quedas":
                return rede.eventos_recentes(7), True
            if acao == "impressoras":
                return rede.texto_impressoras(), True
            if acao == "exportar":
                import os
                caminho = rede.exportar()
                return f"Excel salvo em Documentos, Ghost, Relatórios: {os.path.basename(caminho)}", True
            return rede.consultar(acao, args.get("termo", "")), True

        if nome == "consultar_maquinas":
            from ghost.servicos import rede
            return rede.consultar_agentes(args.get("acao", "listar"), args.get("termo", "")), True

        if nome == "departamentos_rede":
            from ghost.servicos import rede
            acao = args.get("acao", "listar")
            if acao in ("criar", "remover"):
                lista = rede.definir_departamentos(args.get("nomes") or [], remover=acao == "remover")
                return "departamentos agora: " + ", ".join(lista), True
            if acao == "atribuir":
                feitos, nao, amb = rede.atribuir_departamento(args.get("alvos") or [], args.get("departamento") or "")
                return (f"no departamento {args.get('departamento')}: {', '.join(feitos) or 'nenhum'}"
                        + (f"; não achei: {', '.join(nao)}" if nao else "")
                        + (f"; ambíguos (peça o IP): {', '.join(amb)}" if amb else "")), True
            return "departamentos: " + (", ".join(rede.departamentos()) or "nenhum ainda"), True

        if nome == "ensinar_comando":
            from ghost.automacao import automacoes
            de, para = automacoes.normalizar(args.get("frase", "")), automacoes.normalizar(args.get("comando", ""))
            if not de or not para or de == para:
                return "frase ou comando vazio", True
            automacoes.ensinar(de, para)
            return f"aprendido: '{de}' -> '{para}' (vale já, por voz)", True

        if nome == "nomear_maquina":
            from ghost.servicos import rede
            a, n = rede.nomear(args.get("alvo", ""), args.get("apelido"), args.get("responsavel"), args.get("departamento"),
                               args.get("critico"))
            if not a:
                return (f"não achei '{args.get('alvo')}' no inventário" if n == 0
                        else f"'{args.get('alvo')}' corresponde a {n} aparelhos; peça o IP"), True
            if args.get("critico") and a.get("ip"):
                if not rede.responde(a["ip"]):
                    return (f"marcado como crítico: {rede.nome_exibicao(a)} ({a.get('ip')}), MAS ele não respondeu agora "
                            "nem a ping nem às portas comuns; vai aparecer como fora do ar"), True
            return (f"anotado: {rede.nome_exibicao(a)} ({a.get('ip')}), {a.get('responsavel') or ''} "
                    f"{a.get('departamento') or ''}{', crítico' if a.get('critico') else ''}"), True

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
    """Argumentos da ferramenta (texto JSON vindo da IA). Sempre devolve um dicionário."""
    try:
        v = json.loads(texto or "{}")
    except (TypeError, ValueError):
        return {}
    return v if isinstance(v, dict) else {}
