# GHOST — assistente de voz estilo JARVIS

Assistente pessoal para Windows, em Python: você diz **"Ghost, …"** (ou segura **F9**), ele responde em voz e texto, executa ações no computador, controla o mouse por gestos da mão, lê a expressão facial e aprende sobre você com o tempo.

## Funcionalidades

| Área | O que faz |
|---|---|
| Voz | "Ghost, …" sem tecla ou segurando F9 → transcrição com Whisper (Groq), Google e Whisper local como reserva |
| Palavra "Ghost" treinada | "Ghost, treinar ativação": aprende como **você** diz "Ghost" (openWakeWord, local) e reage na hora; continua aprendendo sozinho. Sem treino, usa o Vosk offline |
| Interrupção | Falar por cima, dizer "Ghost" ou apertar F9 enquanto ele fala faz ele parar e ouvir |
| Sem internet | Continua funcionando: transcrição (faster-whisper), IA (Ollama `gemma3:4b`) e voz (Piper) no próprio PC; volta para a nuvem sozinho |
| Memória longa | Todas as conversas com data, pesquisáveis pelo sentido: "o que eu te falei semana passada sobre o fornecedor?" |
| Tela | "o que é esse erro na tela?": captura a janela (ou os monitores) só quando você pede e analisa (Gemini) |
| Notificações | Avisa por voz WhatsApp/Outlook/Teams… (só app e remetente; o texto só se você pedir) |
| Telegram | Pedidos por texto ou áudio pelo celular; resposta por escrito; só o dono é atendido |
| Tarefas longas | "compara as planilhas de setembro e outubro e me avisa": trabalha em segundo plano (só leitura) e avisa ao terminar |
| Lembretes | "me lembra às 15h de…", "quais são meus lembretes?"; fala na hora e mostra aviso na tela |
| IA | Groq (`openai/gpt-oss-120b`), com resposta em streaming falada frase a frase; Gemini como reserva (troca de modelo automática) |
| Personalidade | Estilo JARVIS (elegante, humor seco ocasional, oferece o próximo passo) ou "modo sério" |
| Painel (HUD) | Faixa no topo da tela: em espera / ouvindo / pensando / falando; clique atravessa |
| Resumo da manhã | "bom dia": data, clima (Open-Meteo), lembretes, agenda e e-mails não lidos; automático 1x de manhã |
| Alertas proativos | Disco cheio, memória alta, bateria fraca, internet caiu/voltou, pausa após 90 min, chuva na hora da saída |
| Agenda e e-mail | Somente leitura: Google Workspace (API, quando liberado) e contas pessoais (IMAP + link iCal) |
| Planilhas | Perguntas sobre Excel/CSV ("quanto produzimos ontem?"): a IA escolhe a operação, o cálculo é local |
| Casa inteligente | Pronto para Home Assistant e Tuya/Smart Life: "liga a luz da sala em 30%" |
| Fala | Voz neural `pt-BR-AntonioNeural` (edge-tts), gerada e tocada em paralelo; frases comuns em cache (saem na hora) |
| Aplicativos | Abre/fecha **qualquer app instalado** (lista do Menu Iniciar), com "quis dizer X?" quando o nome não é exato |
| Ferramentas da IA | A IA age no PC por ferramentas (abrir apps, sites, pesquisar, digitar, teclas, comandos do Ghost, consultas de leitura do sistema) e pergunta o propósito quando fica em dúvida |
| Automações | Programas, sites, pesquisa no Google/YouTube, volume, mídia, print, desligar, ditado ("digite ...") e teclas ("aperte enter") |
| WhatsApp | "mande uma mensagem para Fulano dizendo ..." (Desktop ou Web) |
| Gestos | Mouse e atalhos pela mão (MediaPipe), **gestos com as duas mãos** (zoom, visão de tarefas, áreas de trabalho), suporte a dois monitores |
| Cadastro | Tela com abas **Ações** (teclas, comandos de voz, **macros gravadas** do teclado/mouse) e **Gestos** (nativos ou gravados), cada gesto ligado a uma ação |
| Rosto | Leitura de expressão (estimativa) e check-in periódico ("como o senhor está?") |
| Memória | Aprende fatos e padrões de comportamento automaticamente (`memoria_aprendizado.json`) |
| Conversa contínua | Lembra as últimas 12 trocas (inclusive comandos executados); recomeça após 45 min parado |
| Skills por voz | "aprenda uma nova skill": a IA monta os passos com as ferramentas existentes e só salva com o seu "sim" |
| Rotina | Observa só o programa/janela em foco (sem captura de tela), resume padrões e sugere skills |
| Visão | "o que é isso na minha mão?": tira uma foto sob demanda e descreve o objeto (Gemini; detector local de reserva). Não identifica pessoas |
| Saudação | Frase de cumprimento configurável por voz (`preferencias.json`) |
| Pessoas | Fichas ditas por voz (nome, função, telefone, notas), sem biometria; "aqui é Fulano" muda quem está falando |
| Sistema | Inicia com o Windows, roda oculto com log (`ghost.log`), impede duas cópias abertas |

## Instalação

**Guia completo e prático: [INSTALACAO.md](INSTALACAO.md).** Em resumo:

| Situação | O que fazer |
|---|---|
| Primeira vez | `git clone https://github.com/ivanpsd/GHOST-IA.git C:\GHOST` e dois cliques em **`instalar.bat`** |
| Já instalado, versão nova | Dois cliques em **`atualizar.bat`** (mantém chaves, memória, fichas e skills) |
| Parar / ligar | **`parar.bat`** / **`iniciar.bat`** (ele também liga sozinho com o Windows) |

O **vigia** roda o Ghost oculto e o reinicia sozinho se ele cair (para depois de 5 quedas em 10 minutos e mostra um aviso).

**Arquivos de diagnóstico:**
- `ghost.log`: tudo o que o Ghost escreveu (limite de 2 MB; o anterior fica em `ghost.log.1`) e as quedas anotadas pelo vigia.
- `travamentos.log`: onde o programa estava quando caiu por erro dentro de uma biblioteca (som, câmera, Vosk).

**Segurança:** depois que a IA lê algo de fora (e-mail, agenda, planilha, câmera, tela, notificações), qualquer ação no PC pedida
na mesma resposta (digitar, apertar teclas, WhatsApp, abrir sites...) só acontece se você confirmar por voz.

## Comandos de voz (exemplos)

| Fala | Ação |
|---|---|
| "treinar ativação" / "esquecer treino da ativação" | Treina (ou apaga) a palavra "Ghost" na sua voz |
| "o que é esse erro na tela?" / "resume esse documento aberto" | Analisa a tela (só quando pedido) |
| "o que eu te falei semana passada sobre o fornecedor?" | Busca na memória longa |
| "quais notificações chegaram?" / "silenciar notificações por 1 hora" | Notificações do Windows |
| "compara as planilhas de setembro e outubro e me avisa" | Tarefa em segundo plano |
| "abra a calculadora" / "abra o YouTube" | Abre programa ou site |
| "abre o AnyDesk" / "fecha o Excel" | Abre/fecha qualquer aplicativo instalado |
| "quanto espaço livre tenho no disco?" | Consulta do sistema pela IA |
| "pesquise receita de bolo no YouTube" | Pesquisa |
| "mande uma mensagem para Deborah dizendo bom dia" | WhatsApp |
| "digite bom dia equipe" / "aperte enter" | Ditado e teclas |
| "ativar gestos" / "desativar gestos" | Controle por gestos |
| "abrir cadastro de gestos" | Tela de cadastro de gestos e ações |
| "executar ação <nome>" | Roda uma ação cadastrada (ex.: uma macro) |
| "ativar / desativar leitura facial" | Leitura de expressão |
| "como eu estou?" | Estado estimado pela expressão |
| "não me pergunte por 30 minutos" / "pausar check-in" | Controla os check-ins |
| "outro monitor" / "um monitor por vez" | Mouse em dois monitores |
| "aprenda uma nova skill" / "quais skills você sabe?" / "esqueça a skill X" | Skills ensinadas por voz |
| "o que eu fiz hoje?" / "ativar/desativar observação da rotina" | Rotina de uso do PC |
| "esta é a Deborah, minha líder..." / "o que você sabe sobre a Deborah?" | Fichas de pessoas |
| "aqui é o Gustavo" / "aqui é o Ivan" | Quem está falando (por declaração) |
| "o que é isso na minha mão?" / "o que você está vendo?" | Visão pela câmera, sob demanda |
| "me lembra daqui a 20 minutos de…" / "cancela o lembrete do…" | Lembretes |
| "ativar / desativar ativação por voz" | Liga/desliga a escuta da palavra "Ghost" |
| "a partir de agora, me cumprimente dizendo..." | Muda a saudação |
| "bom dia" / "resumo do dia" / "vai chover hoje?" / "minha cidade é Barueri" | Resumo da manhã e clima |
| "esconder painel" / "mostrar painel" | Painel visual (HUD) |
| "modo sério" / "modo Jarvis" | Personalidade |
| "como está o computador?" / "silenciar alertas por 1 hora" / "pausar alertas" | Alertas proativos |
| "como está minha agenda hoje?" / "tenho e-mail novo da minha líder?" / "meus e-mails pessoais" | Agenda e e-mail (leitura) |
| "conectar minha conta Google" | Autoriza a conta do Google Workspace (precisa do `credentials.json`) |
| "quanto produzimos ontem pela planilha de produção?" | Planilhas |
| "conectar casa inteligente" / "liga a luz da sala" / "quais aparelhos você controla?" | Casa inteligente |

## Gestos padrão (editáveis no cadastro)

| Gesto | Ação |
|---|---|
| Só o indicador levantado | Mover o mouse |
| Pinça polegar + indicador | Clique (segurar = arrastar) |
| Indicador em pé + polegar no médio | Clique direito |
| Indicador + médio | Rolar a página |
| Punho fechado 1 s | Pausar/retomar |
| Joinha | Enter |
| Hang loose | Esc |
| Mão aberta deslizando → / ← | Alt+Tab / Voltar |
| Pinça nas duas mãos, afastando/aproximando | Zoom |
| Duas mãos abertas se afastando / aproximando | Visão de tarefas / Área de trabalho |
| Duas mãos abertas deslizando → / ← | Área de trabalho virtual seguinte / anterior |

## Estrutura

| Arquivo | Papel |
|---|---|
| `ghost.py` | Loop principal: voz, IA, fala |
| `automacoes.py` | Comandos locais (executados antes da IA) |
| `memoria.py` | Aprendizado automático de fatos |
| `camera.py` | Câmera compartilhada entre gestos e rosto |
| `gestos_lib.py` / `gestos.py` | Detecção da mão e controle de mouse/teclado |
| `cadastro_gestos.py` | Tela (Tkinter) de cadastro de gestos e ações |
| `macros.py` | Gravação (F10 encerra) e execução de macros |
| `apps.py` | Lista, abre e fecha aplicativos instalados |
| `ferramentas.py` | Ferramentas que a IA pode chamar (conjunto fechado, sem comando livre) |
| `rosto.py` | Leitura de expressão, check-in e padrões de comportamento |
| `conversa.py` | Contexto da conversa (memória de curto prazo) |
| `skills.py` | Skills ensinadas por voz |
| `rotina.py` | Observação da rotina (programa/janela em foco) e sugestões |
| `pessoas.py` | Fichas de pessoas e falante atual |
| `visao.py` | Foto sob demanda + descrição do objeto |
| `preferencias.py` | Preferências como a saudação |
| `ativacao.py` | Palavra de ativação offline e interrupção |
| `lembretes.py` | Lembretes e alarmes |
| `hud.py` | Painel visual no topo da tela |
| `resumo.py` | Resumo da manhã e clima |
| `alertas.py` | Alertas proativos |
| `google_conta.py` | Agenda e Gmail do Google Workspace (API, leitura) |
| `contas_pessoais.py` | E-mail (IMAP) e agenda (iCal) de contas pessoais, leitura |
| `planilhas.py` | Consultas em Excel/CSV, cálculo local |
| `casa.py` | Casa inteligente (Home Assistant / Tuya) |
| `som.py` | Único acesso ao alto-falante e ao microfone (evita travamentos) |
| `eco.py` | Cancelamento de eco (WebRTC) |
| `palavra.py` | Detector de "Ghost" treinado na sua voz |
| `offline.py` | Modo sem internet (Whisper local, Ollama, Piper) |
| `memoria_longa.py` | Histórico completo pesquisável pelo sentido |
| `tela.py` | Captura da tela sob demanda |
| `notificacoes.py` | Avisos das notificações do Windows |
| `telegram_bot.py` | Pedidos pelo celular |
| `tarefas.py` | Tarefas longas em segundo plano |
| `arquivo.py` | Gravação segura de arquivos |
| `vigia.pyw` | Inicia o Ghost e o reinicia se cair |
| `instalar_modelos.py` | Baixa os modelos locais |
| `instalar.bat` / `atualizar.bat` / `parar.bat` / `iniciar.bat` | Instalação, atualização, parar e ligar (ver INSTALACAO.md) |

## Privacidade

- As chaves ficam só no `.env`, que não vai para o Git.
- Nenhuma imagem da câmera é gravada; só números de expressão, mantidos em memória.
- Ficam fora do Git: `.env`, `credentials.json`, `token_google.json`, todos os `.json` pessoais (memória, conversa, skills, pessoas, lembretes, preferências, gestos, aparelhos), `humor_log.jsonl`, `rotina_log.jsonl`, `ghost.log` e `modelos/`.
- A rotina registra apenas o nome do programa e o título da janela (`GUARDAR_TITULOS = False` em `rotina.py` guarda só o programa).
- Fichas de pessoas não usam rosto nem voz: só o que é dito ao Ghost.
- A palavra de ativação é reconhecida no próprio PC; só a frase que começa com "Ghost" vai para a transcrição.
- A visão só tira foto quando você pede; a foto vai ao Gemini para ser descrita e não é salva.
- Agenda e e-mail são **somente leitura** (não envia, não apaga, não marca como lido); dos e-mails só remetente e assunto vão para a IA.
- Planilhas: a IA vê só os nomes das colunas e 3 linhas de exemplo; o cálculo é feito no PC.
- Expressão facial é uma **estimativa**, não um diagnóstico de sentimento.
- A tela só é capturada quando você pede; a imagem vai ao Gemini e não é salva.
- Notificações: lidas do próprio Windows; em voz alta só o app e o remetente, salvo se você pedir o texto.
- Memória longa (`historico_completo.jsonl`) e o treino da palavra (`modelos/palavra/`) ficam só no PC, fora do Git.
- Telegram: só o código do dono (`TELEGRAM_DONO`) é atendido; a tela nunca é enviada.
