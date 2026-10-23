# GHOST — assistente de voz estilo JARVIS

Assistente pessoal para Windows, em Python: você diz **"Ghost, …"** (ou segura **F9**), ele responde em voz e texto, executa ações no computador, controla o mouse por gestos da mão, lê a expressão facial e aprende sobre você com o tempo.

## Funcionalidades

| Área | O que faz |
|---|---|
| Voz | "Ghost, …" sem tecla (palavra de ativação **offline** com Vosk) ou segurando F9 → transcrição com Whisper (Groq), com o Google como reserva |
| Interrupção | Dizer "Ghost" ou apertar F9 enquanto ele fala faz ele parar e ouvir |
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

1. Python 3.13+ no Windows.
2. Instale as dependências:
   ```powershell
   pip install -r requirements.txt
   ```
3. Copie `.env.example` para `.env` e coloque as suas chaves:
   - Groq: https://console.groq.com → API Keys
   - Gemini: https://aistudio.google.com → API Keys
   - Opcionais (contas pessoais, casa inteligente): veja os comentários no `.env.example`
4. Rode:
   ```powershell
   python ghost.py
   ```
   Os modelos de mão e rosto do MediaPipe são baixados sozinhos na primeira vez, para a pasta `modelos/`.
   Para a palavra de ativação, baixe e extraia em `modelos/` o modelo offline
   [vosk-model-small-en-us-0.15](https://alphacephei.com/vosk/models) (sem ele, use o F9).

**Iniciar com o Windows:** crie um atalho para `pythonw.exe ghost.py` (pasta de trabalho = pasta do projeto) em `shell:startup`. Rodando oculto, a saída vai para `ghost.log`.

## Comandos de voz (exemplos)

| Fala | Ação |
|---|---|
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
