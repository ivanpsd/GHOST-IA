# GHOST — assistente de voz estilo JARVIS

Assistente pessoal para Windows, em Python: você diz **"Ghost, …"** (ou segura **F9**), ele responde em voz e texto, executa ações no computador e aprende sobre você com o tempo.

## Funcionalidades

| Área | O que faz |
|---|---|
| Voz | "Ghost, …" sem tecla ou segurando F9 → transcrição com Whisper (Groq) e Google como reserva |
| Palavra "Ghost" treinada | "Ghost, treinar ativação": aprende como **você** diz "Ghost" (openWakeWord, local) e reage na hora; continua aprendendo sozinho. Sem treino, usa o Vosk offline |
| Interrupção | Falar por cima, dizer "Ghost" ou apertar F9 enquanto ele fala faz ele parar e ouvir |
| Memória longa | Todas as conversas com data, pesquisáveis pelo sentido: "o que eu te falei semana passada sobre o fornecedor?" |
| Tela | "o que é esse erro na tela?": captura a janela (ou os monitores) só quando você pede e analisa (Gemini) |
| Notificações | Avisa por voz WhatsApp/Outlook/Teams… (só app e remetente; o texto só se você pedir) |
| Tarefas longas | "compara as planilhas de setembro e outubro e me avisa": trabalha em segundo plano (só leitura) e avisa ao terminar |
| Lembretes | "me lembra às 15h de…", "quais são meus lembretes?"; fala na hora e mostra aviso na tela |
| IA | Groq (`openai/gpt-oss-120b`), com resposta em streaming falada frase a frase; Gemini como reserva (troca de modelo automática) |
| Personalidade | Estilo JARVIS (elegante, humor seco ocasional, oferece o próximo passo) ou "modo sério" |
| Painel | Tela própria do Ghost (janela do Edge em modo aplicativo), com o anel animado no centro e todos os indicadores em volta: estado, máquina, rede, IA, escuta, memória, lembretes, tarefas, notificações, rotina e crônica de eventos. Botão **Exportar** ou "Ghost, exportar indicadores" gera um Excel em `Documentos\Ghost\Relatorios` |
| App do celular | Pelo **Tailscale** (5G, casa, escritório; criptografado) ou só no mesmo Wi-Fi. Pareamento por QR de uso único, **PIN** de 6 dígitos, aparelhos removíveis, ações sensíveis confirmadas no app. Pedidos digitados ou **falados** (com Tailscale); respostas por escrito no celular, sem falar no PC |
| Demonstração | "Ghost, abrir demonstração do painel": abre o painel e o app do celular com dados de exemplo e salva os arquivos em `Documentos\Ghost\Demonstracao` (dá para mandar para alguém ver) |
| Faixa do topo | Faixa discreta mostrando ouvindo / pensando / falando; clique atravessa |
| Resumo da manhã | "bom dia": data, clima (Open-Meteo), lembretes, agenda e e-mails não lidos; automático 1x de manhã |
| Alertas proativos | Disco cheio, memória alta, bateria fraca, internet caiu/voltou, pausa após 90 min, chuva na hora da saída |
| Agenda e e-mail | Somente leitura: Google Workspace (API, quando liberado) e contas pessoais (IMAP + link iCal) |
| Planilhas | Perguntas sobre Excel/CSV ("quanto produzimos ontem?"): a IA escolhe a operação, o cálculo é local |
| Fala | Voz neural `pt-BR-AntonioNeural` (edge-tts), gerada e tocada em paralelo; frases comuns em cache (saem na hora) |
| Aplicativos | Abre/fecha **qualquer app instalado** (lista do Menu Iniciar), com "quis dizer X?" quando o nome não é exato |
| Ferramentas da IA | A IA age no PC por ferramentas (abrir apps, sites, pesquisar, digitar, teclas, comandos do Ghost, consultas de leitura do sistema) e pergunta o propósito quando fica em dúvida |
| Automações | Programas, sites, pesquisa no Google/YouTube, volume, mídia, print, desligar, ditado ("digite ...") e teclas ("aperte enter") |
| WhatsApp | "mande uma mensagem para Fulano dizendo ..." (Desktop ou Web) |
| Gestos e macros | **Desativados** (o código continua no projeto; para religar: `GESTOS_ATIVOS = True` em `ghost\automacao\automacoes.py`) |
| Memória | Aprende fatos e padrões de comportamento automaticamente (`dados\memoria_aprendizado.json`) |
| Conversa contínua | Lembra as últimas 12 trocas (inclusive comandos executados); recomeça após 45 min parado |
| Skills por voz | "aprenda uma nova skill": a IA monta os passos com as ferramentas existentes e só salva com o seu "sim" |
| Skills pela tela | "aprenda uma skill pela tela": o senhor faz a tarefa (Protheus, Excel, qualquer programa), diz "parar de gravar" e revisa no painel. Ele repete achando os botões pelo **texto** (OCR do Windows, sem internet) e pela imagem; para se não achar; senha nunca é gravada; valores que mudam viram pergunta; **datas digitadas viram campos de período**: "faturamento por cliente do mês passado", "… de 1 a 15 de outubro" |
| Rotina | Observa só o programa/janela em foco (sem captura de tela), resume padrões e sugere skills |
| Visão | "o que é isso na minha mão?": tira uma foto sob demanda e descreve o objeto (Gemini; detector local de reserva). Não identifica pessoas |
| Saudação | Frase de cumprimento configurável por voz (`dados\preferencias.json`) |
| Pessoas | Fichas ditas por voz (nome, função, telefone, notas), sem biometria; "aqui é Fulano" muda quem está falando |
| Sistema | Inicia com o Windows, roda oculto com log (`logs\ghost.log`), impede duas cópias abertas, reinicia sozinho se cair |

## Instalação

**Guia completo e prático: [docs/INSTALACAO.md](docs/INSTALACAO.md).** Em resumo:

| Situação | O que fazer |
|---|---|
| Primeira vez | `git clone https://github.com/ivanpsd/GHOST-IA.git C:\GHOST` e dois cliques em **`instalar.bat`** |
| Já instalado, versão nova | Dois cliques em **`atualizar.bat`** (mantém chaves, memória, fichas e skills) |
| Parar / ligar | **`parar.bat`** / **`iniciar.bat`** (ele também liga sozinho com o Windows) |
| Conferir se está tudo certo | **`testar.bat`** (testes automáticos + checagem do código) |

O **vigia** roda o Ghost oculto e o reinicia sozinho se ele cair (para depois de 5 quedas em 10 minutos e mostra um aviso).

**Arquivos de diagnóstico (pasta `logs\`):**
- `logs\ghost.log`: tudo o que o Ghost escreveu (limite de 2 MB; o anterior fica em `ghost.log.1`) e as quedas anotadas pelo vigia.
- `logs\travamentos.log`: onde o programa estava quando caiu por erro dentro de uma biblioteca (som, câmera, Vosk).

**Segurança:** depois que a IA lê algo de fora (e-mail, agenda, planilha, câmera, tela, notificações), qualquer ação no PC pedida
na mesma resposta (digitar, apertar teclas, WhatsApp, abrir sites...) só acontece se você confirmar por voz.

## Comandos de voz (exemplos)

| Fala | Ação |
|---|---|
| "oi Ghost" / "olá Ghost" | **Conversa contínua**: depois disso fale sem dizer "Ghost" (encerra sozinha após 5 min sem falar) |
| "tchau Ghost" / "boa noite Ghost" | **Dormir**: ignora tudo e não fala sozinho (alertas, notificações) até ser chamado; lembretes continuam |
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
| "outro monitor" / "um monitor por vez" | Mouse em dois monitores |
| "aprenda uma nova skill" / "quais skills você sabe?" / "esqueça a skill X" / "mostre a skill X" | Skills ensinadas por voz |
| "aprenda uma skill pela tela" → "parar de gravar" (ou F10) → "teste a skill" / "remova o passo 3" / "o passo 4 muda" / "salve a skill como …" | Skills gravadas na tela (F10 também interrompe a execução) |
| "o que eu fiz hoje?" / "ativar/desativar observação da rotina" | Rotina de uso do PC |
| "esta é a Deborah, minha líder..." / "o que você sabe sobre a Deborah?" | Fichas de pessoas |
| "aqui é o Gustavo" / "aqui é o Ivan" | Quem está falando (por declaração) |
| "o que é isso na minha mão?" / "o que você está vendo?" | Visão pela câmera, sob demanda |
| "me lembra daqui a 20 minutos de…" / "cancela o lembrete do…" | Lembretes |
| "ativar / desativar ativação por voz" | Liga/desliga a escuta da palavra "Ghost" |
| "a partir de agora, me cumprimente dizendo..." | Muda a saudação |
| "bom dia" / "resumo do dia" / "vai chover hoje?" / "minha cidade é Barueri" | Resumo da manhã e clima |
| "abrir painel" / "fechar painel" | Tela de indicadores |
| "exportar indicadores" | Excel com os indicadores em `Documentos\Ghost\Relatorios` |
| "conectar celular" / "desconectar celular" | Liga o acesso e mostra o QR de pareamento / desliga o acesso |
| "remover os celulares" / "trocar PIN do celular" | Tira todos os aparelhos / apaga o PIN (todos pareiam de novo) |
| "abrir demonstração do painel" | Painel e app do celular com dados de exemplo |
| "esconder faixa" / "mostrar faixa" | Faixa do topo |
| "modo sério" / "modo Jarvis" | Personalidade |
| "como está o computador?" / "silenciar alertas por 1 hora" / "pausar alertas" | Alertas proativos |
| "como está minha agenda hoje?" / "tenho e-mail novo da minha líder?" / "meus e-mails pessoais" | Agenda e e-mail (leitura) |
| "conectar minha conta Google" | **Desativado** por enquanto (`GOOGLE_ATIVO` em `ghost\servicos\google_conta.py`) |
| "quanto produzimos ontem pela planilha de produção?" | Planilhas |

## Estrutura

```
C:\GHOST
├── ghost\                  o programa (pacote Python)
│   ├── app.py              laço principal: voz -> comandos locais ou IA -> fala
│   ├── vigia.py            inicia o Ghost e o reinicia se cair (é o que liga com o Windows)
│   ├── instalar_modelos.py baixa os modelos locais
│   ├── nucleo\             caminhos, gravação segura, preferências, Windows, painel de indicadores, faixa do topo
│   ├── voz\                microfone/alto-falante, palavra "Ghost", eco
│   ├── ia\                 ferramentas da IA, conversa, memórias, tarefas, skills, pessoas
│   ├── automacao\          comandos locais, aplicativos, planilhas (macros desativadas)
│   ├── visao\              câmera, foto, tela (gestos e cadastro desativados)
│   └── servicos\           alertas, lembretes, resumo do dia, rotina, notificações, Google, e-mail/agenda pessoais
├── tests\                  testes automáticos (testar.bat)
├── scripts\                instalação, atualização, parada e testes (chamados pelos .bat)
├── docs\                   INSTALACAO.md e ARQUITETURA.md
├── dados\                  SEUS dados: memória, fichas, skills, lembretes, treino da voz... (fora do Git)
├── logs\                   ghost.log e travamentos.log (fora do Git)
├── modelos\                modelos baixados (fora do Git)
├── *.bat                   instalar, atualizar, iniciar, parar, testar
├── .env                    suas chaves (fora do Git; modelo em .env.example)
└── requirements.txt        bibliotecas
```

Como as partes se conversam (fluxo de um pedido, threads, proteções e onde mexer em cada coisa):
**[docs/ARQUITETURA.md](docs/ARQUITETURA.md)**.

Rodar vendo o terminal (para diagnóstico): `parar.bat` e depois `.\.venv\Scripts\python.exe -m ghost`.

## Privacidade

- As chaves ficam só no `.env`, que não vai para o Git.
- Ficam fora do Git: `.env` e as pastas `dados\` (memória, conversa, skills, pessoas, lembretes, preferências, rotina, histórico, treino da voz, `credentials.json`, `token_google.json`), `logs\`, `modelos\` e `prints\`.
- A rotina registra apenas o nome do programa e o título da janela (`GUARDAR_TITULOS = False` em `ghost\servicos\rotina.py` guarda só o programa).
- Fichas de pessoas não usam biometria: só o que é dito ao Ghost.
- A palavra de ativação é reconhecida no próprio PC; só a frase que começa com "Ghost" vai para a transcrição.
- A visão só tira foto quando você pede; a foto vai ao Gemini para ser descrita e não é salva.
- Agenda e e-mail são **somente leitura** (não envia, não apaga, não marca como lido); dos e-mails só remetente e assunto vão para a IA.
- Planilhas: a IA vê só os nomes das colunas e 3 linhas de exemplo; o cálculo é feito no PC.
- A tela só é capturada quando você pede; a imagem vai ao Gemini e não é salva.
- Notificações: lidas do próprio Windows; em voz alta só o app e o remetente, salvo se você pedir o texto.
- Memória longa (`dados\historico_completo.jsonl`) e o treino da palavra (`dados\palavra\`) ficam só no PC, fora do Git.
