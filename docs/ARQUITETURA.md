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
F9 ─────────────────────────┼─► fila_comandos ─► app (laço principal)
Telegram ─► servicos/telegram_bot ┘                 │
                                                    ├─ transcrever (Groq Whisper → Google → Whisper local)
                                                    ├─ confere "Ghost" no começo (só ativação por voz)
                                                    ├─ modos: "oi Ghost" / "tchau Ghost"
                                                    ├─ automacao/automacoes.executar  (comandos locais, sem IA)
                                                    └─ IA: Groq → Gemini → Ollama (com ferramentas de ia/ferramentas)
                                                                │
                              texto_queue ─► gerador de voz (edge-tts / Piper) ─► audio_queue ─► voz/som
```

- **Ativação** (`voz/ativacao.py`): um único fluxo do microfone (`voz/som.py`) alimenta o Vosk e o detector treinado
  (`voz/palavra.py`). Modos: `normal`, `conversa` (fala sem dizer "Ghost" por 5 min) e `dormindo` (ignora tudo até
  "oi Ghost" ou "Ghost, ..."). Se o microfone travar (fone tirado, suspensão), reabre sozinho.
- **Fala**: cada frase recebe a "geração" atual; interromper (`parar_fala`) muda a geração e as frases velhas são descartadas
  em vez de tocar atrasadas. `voz/eco.py` tira o som do próprio Ghost do microfone para você poder interrompê-lo falando.
- **Canal** (`nucleo/canal.py`): num pedido do Telegram, o que o Ghost "fala" vai por escrito para o celular. O destino é
  herdado pelas threads abertas com `canal.thread()`.

## Proteções

| Risco | Proteção | Onde |
|---|---|---|
| Texto de fora (e-mail, tela, planilha) mandar o PC fazer algo | Depois de uma ferramenta **EXTERNA**, qualquer **AÇÃO** pede confirmação por voz | `ia/ferramentas.py` (`EXTERNAS`, `ACOES`), `app._executar_ferramentas` |
| Arquivo pela metade (queda de energia) | Grava em `.tmp` + `fsync` + troca atômica; arquivo estragado vira `.corrompido` e **não** é sobrescrito | `nucleo/arquivo.py` |
| Duas threads no áudio (travava o PortAudio) | Um só acesso ao alto-falante/microfone, com trava | `voz/som.py` |
| Queda em biblioteca nativa | `faulthandler` + vigia | `app.py`, `vigia.py` |
| IA travada | Tempo limite em cada modelo e troca automática (Groq → Gemini → Ollama) | `app.consultar_ia_streaming` |
| Sem internet | Transcrição, IA e voz locais | `voz/offline.py` |
| Comando por engano (conversa da sala) | Detector treinado na sua voz + conferência do "Ghost" pelo Whisper + volume mínimo da sua voz | `voz/palavra.py`, `voz/ativacao.py`, `app.py` |
| Mensagem do WhatsApp para a pessoa errada | Contato só é trocado pela ficha quando há UMA correspondência exata | `ia/pessoas.resolver_contato` |
| Token do Telegram em log | Erros passam por `_limpo()` | `servicos/telegram_bot.py` |

## Onde mexer

| Quero mudar... | Arquivo |
|---|---|
| Personalidade, instruções da IA, modelos usados | `ghost/app.py` (`PERSONALIDADES`, `SYSTEM_INSTRUCTION`, `MODELOS_GROQ`, `MODELOS_GEMINI`) |
| Um comando local novo ("Ghost, faça X" sem IA) | `ghost/automacao/automacoes.py` (uma função `_tratar_...` e a chamada em `executar`) |
| Uma ferramenta nova para a IA | `ghost/ia/ferramentas.py` (`TOOLS`, `executar` e classificar em `EXTERNAS`/`ACOES`) |
| Sensibilidade do microfone / da palavra "Ghost" | `ghost/voz/ativacao.py` (`FATOR_DONO`, `FATOR_INTERRUPCAO`), `ghost/voz/palavra.py` (`LIMIAR_MINIMO`) |
| Alertas (disco, bateria, pausa, chuva) | `ghost/servicos/alertas.py` |
| Gestos padrão | `ghost/visao/gestos_lib.py` |
| Onde ficam os arquivos | `ghost/nucleo/caminhos.py` |

## Pastas de dados

| Pasta | Conteúdo | No Git? |
|---|---|---|
| `dados/` | memória, conversa, fichas, skills, lembretes, preferências, gestos, aparelhos, humor, rotina, histórico, treino da voz, `credentials.json`, `token_google.json` | não |
| `logs/` | `ghost.log` (2 MB + 1 anterior), `travamentos.log` | não |
| `modelos/` | Vosk, Whisper local, Piper, MediaPipe, base do detector, cache de voz | não |
| `prints/` | capturas de tela pedidas por voz | não |

## Testes

`testar.bat` roda o `ruff` (erros de código) e o `pytest` (`tests/`). Os testes não tocam nos seus dados: cada um usa
uma pasta temporária. Testes que precisam das bibliotecas do Windows (áudio, teclado) só rodam no Windows.
