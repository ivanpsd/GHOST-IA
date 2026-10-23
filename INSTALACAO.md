# GHOST: instalar e atualizar

Tudo é feito por **3 arquivos de dois cliques** dentro da pasta do Ghost:

| Arquivo | Quando usar |
|---|---|
| `instalar.bat` | **Primeira vez** num computador (ou para refazer tudo do zero) |
| `atualizar.bat` | Já está instalado e saiu **uma versão nova** no GitHub |
| `parar.bat` | Parar o Ghost que roda escondido (para usar com terminal ou mexer nos arquivos) |

Requisitos: Windows 10/11, internet na instalação e ~6 GB livres em disco.

---

## 1. Primeira instalação

**Passo 1. Baixe o projeto** (escolha uma opção):

- **Com Git** (recomendado, porque permite atualizar com dois cliques):
  ```powershell
  winget install --id Git.Git -e
  cd C:\
  git clone https://github.com/ivanpsd/GHOST-IA.git GHOST
  ```
- **Sem Git:** no GitHub, clique em *Code > Download ZIP* e extraia em `C:\GHOST`.
  Nesse caso o `atualizar.bat` não funciona; para atualizar, baixe o ZIP de novo.

**Passo 2. Dê dois cliques em `C:\GHOST\instalar.bat`.** Ele faz sozinho, nesta ordem:

1. Instala o **Python 3.13**, se ainda não existir.
2. Cria o ambiente `.venv` e instala as bibliotecas.
3. Cria o arquivo **`.env`** e abre no Bloco de Notas. Preencha as duas chaves, **salve** e feche o Bloco de Notas para a instalação continuar:
   - `GROQ_API_KEY`: em https://console.groq.com, menu *API Keys*.
   - `GEMINI_API_KEY`: em https://aistudio.google.com, menu *API Keys*.
4. Instala o **Ollama** (IA sem internet).
5. Baixa o modelo da palavra **"Ghost"** (Vosk).
6. Baixa os **modelos locais** (~4 GB; demora na 1ª vez).
7. Coloca o Ghost para **iniciar com o Windows** e já o liga.

**Passo 3. Treine a palavra de ativação.** Diga **"Ghost, treinar ativação"** e siga as instruções (~1 minuto):

1. Diga "Ghost" 8 vezes, sempre depois do bipe.
2. Fale qualquer coisa por 20 segundos.
3. Fique 5 segundos em silêncio.

---

## 2. Atualizar para a última versão

Dê dois cliques em **`atualizar.bat`**. Ele:

1. Para o Ghost.
2. Baixa a versão nova do GitHub (`git pull`).
3. Instala as bibliotecas novas, se houver.
4. Baixa os modelos que faltarem.
5. Religa o Ghost.

**O que é mantido** (não vai para o GitHub e nunca é apagado):

- `.env` (chaves)
- memória
- fichas de pessoas
- skills
- lembretes
- gestos
- histórico das conversas
- treino da palavra "Ghost"

> Se o `git pull` reclamar de "alterações locais", algum arquivo do projeto foi editado à mão.
> Rode `git status` na pasta para ver qual. Para descartar a edição e ficar com a versão do GitHub: `git checkout -- nome_do_arquivo`.

---

## 3. Uso do dia a dia

| Quero... | Faça |
|---|---|
| Ligar o Ghost | Ele liga sozinho com o Windows; ou dois cliques em `iniciar.bat` |
| Desligar o Ghost | `parar.bat` |
| Ver o que ele está fazendo por dentro | Pare (`parar.bat`) e rode na pasta: `.\.venv\Scripts\python.exe ghost.py` |
| Ver erros | Abra `ghost.log`; se ele caiu sozinho, veja também `travamentos.log` |

O **vigia** reinicia o Ghost se ele cair. Se cair 5 vezes em 10 minutos, o vigia desiste e mostra um aviso na tela.

---

## 4. Opcionais (no arquivo `.env`, depois reinicie o Ghost)

| Recurso | O que colocar no `.env` |
|---|---|
| **Telegram** (falar com o Ghost pelo celular) | 1) No Telegram, abra o @BotFather, mande `/newbot` e copie o token. 2) `TELEGRAM_TOKEN=token`. 3) Reinicie o Ghost e mande "oi" para o seu bot: ele responde com o seu código. 4) `TELEGRAM_DONO=código` e reinicie de novo. |
| **E-mail pessoal** (leitura) | `EMAIL1_USUARIO`, `EMAIL1_SENHA` (senha de app) e `EMAIL1_NOME`. Detalhes em `.env.example`. |
| **Agenda pessoal** (leitura) | `AGENDA1_URL` (link secreto iCal) e `AGENDA1_NOME` |
| **Casa inteligente** | `HA_URL` + `HA_TOKEN` (Home Assistant) ou `TUYA_API_KEY` / `TUYA_API_SECRET`. Depois diga "Ghost, conectar casa inteligente". |
| **Google Workspace** (empresa) | Precisa do administrador liberar o Google Cloud. Coloque o `credentials.json` na pasta. |

---

## 5. Levar os seus dados para outro computador

O GitHub guarda **só o programa**. O que o Ghost aprendeu fica só no PC.

Para levar para outro computador:

1. Instale o Ghost no PC novo pelo `instalar.bat`.
2. Dê dois cliques em `parar.bat` nos dois computadores.
3. Copie da pasta `C:\GHOST` antiga para a nova:
   - os arquivos `.env`, `*.json` e `*.jsonl`;
   - a pasta `modelos\palavra`.
4. Ligue o Ghost no PC novo pelo `iniciar.bat`.

---

## 6. Problemas comuns

| Sintoma | Causa provável e solução |
|---|---|
| O `instalar.bat` fecha com erro de Python | Instale o Python 3.13 por python.org (marque "Add to PATH") e rode de novo |
| "não autorizado" ao abrir o `.bat` | Clique com o botão direito no arquivo > Propriedades > Desbloquear |
| Ele não ouve "Ghost" | Confira o microfone padrão do Windows; diga "Ghost, treinar ativação" |
| Ele responde sozinho a conversas da sala | Treine a ativação; no `ativacao.py`, aumente `FATOR_DONO` |
| Ele para de falar sem motivo | No `ativacao.py`, aumente `FATOR_INTERRUPCAO` |
| Sem internet, ele fica mudo | Rode `atualizar.bat`: ele baixa os modelos locais que faltarem |
