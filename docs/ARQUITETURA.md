# GHOST: arquitetura

Mapa de como as partes se conversam, para saber **onde mexer** em cada coisa.

## Como o Ghost liga

```
Windows (atalho GHOST.lnk)  ->  pythonw -m ghost.vigia  ->  python -m ghost  ->  ghost.app.main()
```

1. **`ghost/vigia.py`**: abre o Ghost e o reabre se cair. Saída 0 (já estava aberto) ou 3 (falta chave no `.env`):
   não reabre. 5 quedas em 10 minutos: desiste e mostra um aviso.
2. **`ghost/app.py` → `main()`**:
   - `_preparar_processo()`: vai para a pasta do Ghost, **migra** os arquivos da versão antiga (`nucleo/caminhos.migrar`),
     manda a saída para `logs/ghost.log`, liga o `faulthandler` (`logs/travamentos.log`), impede duas cópias (mutex)
     e carrega as bibliotecas nativas (onnxruntime, ctranslate2) **antes** de câmera e microfone (carregadas depois,
     numa thread, derrubavam o processo).
   - `_iniciar_clientes()`: lê o `.env` e cria os clientes Groq e Gemini. Sem chave: aviso na tela e saída 3.
   - `iniciar_ghost()`: liga cada serviço (um que falhe não derruba os outros) e entra no laço principal.

## O caminho de um pedido

```
microfone ─► voz/ativacao ──┐
F9 ─────────────────────────┴─► fila_comandos ─► app (laço principal)
                                                    │
                                                    ├─ transcrever (Groq Whisper → Google)
                                                    ├─ confere "Ghost" no começo (só ativação por voz)
                                                    ├─ modos: "oi Ghost" / "tchau Ghost"
                                                    ├─ automacao/automacoes.executar  (comandos locais, sem IA)
                                                    └─ IA: Groq → Gemini (com ferramentas de ia/ferramentas)
                                                                │
                              texto_queue ─► gerador de voz (edge-tts, com cache) ─► audio_queue ─► voz/som
```

- **Ativação** (`voz/ativacao.py`): um único fluxo do microfone (`voz/som.py`) alimenta o Vosk e o detector treinado
  (`voz/palavra.py`). Modos: `normal`, `conversa` (fala sem dizer "Ghost" por 5 min) e `dormindo` (ignora tudo até
  "oi Ghost" ou "Ghost, ..."). Se o microfone travar (fone tirado, suspensão), reabre sozinho.
- **Fala**: cada frase recebe a "geração" atual; interromper (`parar_fala`) muda a geração e as frases velhas são descartadas
  em vez de tocar atrasadas. `voz/eco.py` tira o som do próprio Ghost do microfone para você poder interrompê-lo falando.

## Painel de indicadores

`nucleo/painel.py` liga um servidor só local (`127.0.0.1`, com chave aleatória por sessão) e abre a página
`nucleo/painel_web/index.html` no Edge em modo aplicativo. A página lê `/estado` a cada segundo. O resto do Ghost só avisa
o painel (`painel.estado`, `fala`, `contar`, `medir`, `evento`); nada no painel derruba o Ghost.
Exportar (`/exportar`, botão ou voz) gera um Excel com Resumo, Histórico (1 linha por minuto, últimas 24 h), Eventos e Rotina.
Aberta fora do Ghost (sem a chave), a mesma página roda uma demonstração com dados de exemplo
(`painel.criar_demonstracao()` grava essa versão em `Documentos\Ghost\Demonstracao`). O desenho do anel fica em
`painel_web/nucleo.js`, usado pelo painel e pelo app do celular.

**App do celular** (`nucleo/celular.py`): servidor próprio (porta 8766), separado do painel do PC.
- **Caminho de rede:** com Tailscale ligado, o servidor escuta só em `127.0.0.1` e o `tailscale serve` o publica em
  `https://<pc>.<rede>.ts.net` (criptografado, só para os aparelhos da sua conta). Sem Tailscale, escuta na rede local
  apenas se todas as redes ativas do Windows forem Privadas/Domínio; uma thread desliga o acesso se aparecer rede Pública.
- **Pareamento:** código de 6 caracteres, 5 min, uso único, 5 tentativas. Cria o aparelho com chave própria
  (guardada como SHA-256) e, na 1ª vez, o PIN (PBKDF2, 200 mil iterações, com sal) em `dados/celular.json`.
- **Sessão:** o PIN abre uma sessão de 12 h (só em memória; reiniciar o Ghost pede o PIN de novo). 5 PINs errados:
  bloqueio de 15 min; 15 seguidos: o aparelho é removido.
- **Rotas pela rede:** `/celular`, `/parear` (a página), `/api/parear`, `/api/entrar`, `/api/estado`, `/api/comando`,
  `/api/audio`, `/api/sair`. Exportar, QR e lista de aparelhos são só no painel do PC.
- **Pedidos:** entram na mesma fila da voz com `origem = "celular"`. `app._atender_celular` troca o destino da fala
  (`nucleo/canal.py`) para o celular; `automacoes.comando_sensivel()` faz WhatsApp, digitar, teclas, fechar, desligar e skills
  pedirem confirmação; e qualquer ferramenta de AÇÃO pedida pela IA também pede (mesma regra do conteúdo externo).

## Skills gravadas na tela

`automacao/demonstracao.py` grava cliques, digitação, teclas e rolagem (pynput) com uma foto da janela em cada clique
(`visao/olho.py`, PrintWindow). Ao parar, o OCR do Windows lê cada foto e guarda o texto do clique ("Incluir") ou o
rótulo do campo ("Cliente"), um recorte de imagem e a posição relativa. Na execução, para cada clique: acha/foca a janela
(pelo programa e nome base do título; se não estiver aberta, tenta abrir pelo menu Iniciar), espera o texto aparecer
(OCR a cada ~0,8 s, até 25 s), senão procura o recorte (OpenCV), senão a posição relativa (só se a janela tiver o mesmo
tamanho). Não achou: para e avisa. Digitação depois de clicar perto de "Senha" não é gravada (o Ghost pede na hora);
digitação marcada como variável vira pergunta antes de começar (`automacoes.perguntar`). Fotos em `dados/skills/<id>/`.
Datas digitadas na gravação (ex.: `01/10/2026`) viram campos de data com papel início/fim pelo rótulo ("Da Data", "Até a
Data"); na execução, `automacao/periodo.py` tira o período do próprio pedido ("mês passado", "de 1 a 15 de outubro",
"semana passada", "últimos 7 dias"…), pergunta uma vez se não houver, e usa a IA só como último recurso. A skill com campo
variável aceita o gatilho seguido do período. Data escolhida no calendário (clique no botão do
calendário e depois no dia) é trocada na gravação por "clicar no campo ao lado do rótulo" + "digitar a data". Listas que abrem fora da janela (sem título) são procuradas na tela toda.

## Proteções

| Risco | Proteção | Onde |
|---|---|---|
| Celular perdido ou link vazado | Pareamento de uso único + PIN + aparelhos removíveis + Tailscale | `nucleo/celular.py` |
| Pedido do celular mexer no PC sem querer | Ações sensíveis pedem "Sim, confirmo" no app | `automacoes.comando_sensivel`, `app._atender_celular` |
| Texto de fora (e-mail, tela, planilha) mandar o PC fazer algo | Depois de uma ferramenta **EXTERNA**, qualquer **AÇÃO** pede confirmação por voz | `ia/ferramentas.py` (`EXTERNAS`, `ACOES`), `app._executar_ferramentas` |
| Arquivo pela metade (queda de energia) | Grava em `.tmp` + `fsync` + troca atômica; arquivo estragado vira `.corrompido` e **não** é sobrescrito | `nucleo/arquivo.py` |
| Duas threads no áudio (travava o PortAudio) | Um só acesso ao alto-falante/microfone, com trava | `voz/som.py` |
| Queda em biblioteca nativa | `faulthandler` + vigia | `app.py`, `vigia.py` |
| IA travada | Tempo limite em cada modelo e troca automática (Groq → Gemini) | `app.consultar_ia_streaming` |
| Sem internet | Avisa "Senhor, estou sem internet" (frase guardada no cache de voz); comandos voltam sozinhos com a rede | `app.SemInternet` |
| Comando por engano (conversa da sala) | Detector treinado na sua voz + conferência do "Ghost" pelo Whisper + volume mínimo da sua voz | `voz/palavra.py`, `voz/ativacao.py`, `app.py` |
| Mensagem do WhatsApp para a pessoa errada | Contato só é trocado pela ficha quando há UMA correspondência exata | `ia/pessoas.resolver_contato` |

## Onde mexer

| Quero mudar... | Arquivo |
|---|---|
| Personalidade, instruções da IA, modelos usados | `ghost/app.py` (`PERSONALIDADES`, `SYSTEM_INSTRUCTION`, `MODELOS_GROQ`, `MODELOS_GEMINI`) |
| Um comando local novo ("Ghost, faça X" sem IA) | `ghost/automacao/automacoes.py` (uma função `_tratar_...` e a chamada em `executar`) |
| Uma ferramenta nova para a IA | `ghost/ia/ferramentas.py` (`TOOLS`, `executar` e classificar em `EXTERNAS`/`ACOES`) |
| Sensibilidade do microfone / da palavra "Ghost" | `ghost/voz/ativacao.py` (`FATOR_DONO`, `FATOR_INTERRUPCAO`), `ghost/voz/palavra.py` (`LIMIAR_MINIMO`) |
| Alertas (disco, bateria, pausa, chuva) | `ghost/servicos/alertas.py` |
| Religar gestos e macros | `ghost/automacao/automacoes.py` (`GESTOS_ATIVOS = True`) |
| Onde ficam os arquivos | `ghost/nucleo/caminhos.py` |

## Pastas de dados

| Pasta | Conteúdo | No Git? |
|---|---|---|
| `dados/` | memória, conversa, fichas, skills, lembretes, preferências, rotina, histórico, treino da voz, `credentials.json`, `token_google.json` | não |
| `logs/` | `ghost.log` (2 MB + 1 anterior), `travamentos.log` | não |
| `modelos/` | Vosk, MediaPipe, base do detector, cache de voz | não |
| `prints/` | capturas de tela pedidas por voz | não |

## Testes

`testar.bat` roda o `ruff` (erros de código) e o `pytest` (`tests/`). Os testes não tocam nos seus dados: cada um usa
uma pasta temporária. Testes que precisam das bibliotecas do Windows (áudio, teclado) só rodam no Windows.
