# GHOST — assistente de voz estilo JARVIS

Assistente pessoal para Windows, em Python: você fala segurando **F9**, ele responde em voz e texto, executa ações no computador, controla o mouse por gestos da mão, lê a expressão facial e aprende sobre você com o tempo.

## Funcionalidades

| Área | O que faz |
|---|---|
| Voz | Push-to-talk (F9) → transcrição com Whisper (Groq), com o Google como reserva |
| IA | Groq (`openai/gpt-oss-120b`), com resposta em streaming falada frase a frase; Gemini como reserva |
| Fala | Voz neural `pt-BR-AntonioNeural` (edge-tts), gerada e tocada em paralelo |
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
4. Rode:
   ```powershell
   python ghost.py
   ```
   Os modelos de mão e rosto do MediaPipe são baixados sozinhos na primeira vez, para a pasta `modelos/`.

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

## Privacidade

- As chaves ficam só no `.env`, que não vai para o Git.
- Nenhuma imagem da câmera é gravada; só números de expressão, mantidos em memória.
- Ficam fora do Git: `memoria_aprendizado.json`, `conversa_recente.json`, `humor_log.jsonl`, `rotina_log.jsonl`, `skills.json`, `pessoas.json`, `gestos_cadastro.json` e `ghost.log`.
- A rotina registra apenas o nome do programa e o título da janela (`GUARDAR_TITULOS = False` em `rotina.py` guarda só o programa).
- Fichas de pessoas não usam rosto nem voz: só o que é dito ao Ghost.
- Expressão facial é uma **estimativa**, não um diagnóstico de sentimento.
