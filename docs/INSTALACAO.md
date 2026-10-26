# GHOST: instalar e atualizar

Tudo é feito por **arquivos de dois cliques** dentro da pasta do Ghost:

| Arquivo | Quando usar |
|---|---|
| `instalar.bat` | **Primeira vez** num computador (ou para refazer tudo do zero) |
| `atualizar.bat` | Já está instalado e saiu **uma versão nova** no GitHub |
| `iniciar.bat` | Ligar o Ghost (ele também liga sozinho com o Windows) |
| `parar.bat` | Parar o Ghost que roda escondido (para usar com terminal ou mexer nos arquivos) |
| `testar.bat` | Conferir se a instalação está íntegra (testes automáticos + checagem do código) |

Requisitos: Windows 10/11, internet na instalação e ~2 GB livres em disco.

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
4. Baixa o modelo da palavra **"Ghost"** (Vosk).
5. Baixa os **modelos locais** (~400 MB).
6. Coloca o Ghost para **iniciar com o Windows** e já o liga.

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
- a pasta **`dados\`**: memória, fichas de pessoas, skills, lembretes, histórico das conversas, treino da palavra "Ghost"
- a pasta `modelos\` (não baixa de novo)

### Vindo de uma versão antiga (antes da 8.0, com os arquivos `.py` soltos na pasta)

A versão 8.0 reorganizou o projeto em pastas (`ghost\`, `dados\`, `logs\`...). Para atualizar:

1. Dê dois cliques em **`atualizar.bat`**. O `atualizar.bat` antigo baixa a versão nova, mas não sabe religar o Ghost no formato novo (pode aparecer um erro no fim: é esperado).
2. Dê dois cliques em **`atualizar.bat` de novo**. Agora é o novo: ele refaz o atalho da inicialização e liga o Ghost.

Na primeira vez que a versão nova liga, ela **move sozinha** os seus arquivos pessoais (memória, fichas, skills, lembretes,
preferências, histórico, `credentials.json`, `token_google.json`, treino da palavra "Ghost") para `dados\`, e o `ghost.log`
para `logs\`. Nada é apagado; se um arquivo já existir no destino, o antigo fica onde está.

> Se o `git pull` reclamar de "alterações locais", algum arquivo do projeto foi editado à mão.
> Rode `git status` na pasta para ver qual. Para descartar a edição e ficar com a versão do GitHub: `git checkout -- nome_do_arquivo`.

---

## 3. Uso do dia a dia

| Quero... | Faça |
|---|---|
| Ligar o Ghost | Ele liga sozinho com o Windows; ou dois cliques em `iniciar.bat` |
| Desligar o Ghost | `parar.bat` |
| Ver o que ele está fazendo por dentro | Pare (`parar.bat`) e rode na pasta: `.\.venv\Scripts\python.exe -m ghost` |
| Ver erros | Abra `logs\ghost.log`; se ele caiu sozinho, veja também `logs\travamentos.log` |
| Conferir se está tudo certo | `testar.bat` (deve terminar com "Tudo certo.") |

O **vigia** reinicia o Ghost se ele cair. Se cair 5 vezes em 10 minutos, o vigia desiste e mostra um aviso na tela.
Se faltar uma chave no `.env`, o Ghost mostra um aviso e o vigia **não** fica reiniciando: corrija o `.env` e rode `iniciar.bat`.

---

## 4. Opcionais (no arquivo `.env`, depois reinicie o Ghost)

| Recurso | O que colocar no `.env` |
|---|---|
| **E-mail pessoal** (leitura) | `EMAIL1_USUARIO`, `EMAIL1_SENHA` (senha de app) e `EMAIL1_NOME`. Detalhes em `.env.example`. |
| **Agenda pessoal** (leitura) | `AGENDA1_URL` (link secreto iCal) e `AGENDA1_NOME` |
| **Google Workspace** (empresa) | Precisa do administrador liberar o Google Cloud. Coloque o `credentials.json` na pasta `dados\` e diga "Ghost, conectar minha conta Google". |

---

## 4b. App do celular (com segurança e no 5G)

**Passo 1. Tailscale (uma vez, ~5 minutos; recomendado).** É o que deixa usar no 5G e criptografa tudo.

1. No PC: baixe em https://tailscale.com/download/windows, instale e entre com a sua conta (Google ou Microsoft).
2. No celular: instale o app **Tailscale** (Play Store / App Store) e entre com a **mesma conta**. Deixe ligado.
3. Na 1ª vez que você pedir o QR, o Ghost pode avisar que é preciso ligar os **certificados HTTPS** na sua conta
   Tailscale: ele mostra o link; abra, clique em *Enable* e peça o QR de novo.

Sem Tailscale o app ainda funciona, mas só no mesmo Wi-Fi, sem criptografia, e só se a rede do Windows for Privada ou de
Domínio (em rede Pública ele desliga sozinho). Na 1ª vez o Windows pergunta se o Python pode usar a rede: marque só
**Redes privadas**.

**Passo 2. Parear o celular.**

1. Diga **"Ghost, conectar celular"** (ou clique em **Celular** no painel). Aparecem um QR e um código de 6 letras
   (valem 5 minutos e uma vez só).
2. Aponte a câmera do celular para o QR. Dê um nome ao aparelho e **crie o PIN** de 6 números (nos próximos aparelhos,
   use o mesmo PIN).
3. **Adicionar à tela inicial** (Android: menu ⋮; iPhone: botão Compartilhar). No iPhone, o ícone da tela inicial guarda os
   dados separado do Safari: se ele pedir para parear, abra o app pelo ícone e digite o código de 6 letras do painel.

**No dia a dia:** o app pede o PIN ao abrir (a sessão vale 12 h; o botão **Travar** encerra na hora). Com Tailscale aparece
o botão **●** para falar com o Ghost. Ações importantes (WhatsApp, digitar, apertar teclas, fechar programas, desligar o PC,
rodar skills) pedem **Sim, confirmo** no app.

**Se perder o celular:** no painel, **Celular → Remover** no aparelho (ou diga "Ghost, remover os celulares").
Esqueceu o PIN: "Ghost, trocar PIN do celular" (apaga o PIN e todos os aparelhos; pareie de novo).

---

## 5. Levar os seus dados para outro computador

O GitHub guarda **só o programa**. O que o Ghost aprendeu fica só no PC.

Para levar para outro computador:

1. Instale o Ghost no PC novo pelo `instalar.bat`.
2. Dê dois cliques em `parar.bat` nos dois computadores.
3. Copie da pasta `C:\GHOST` antiga para a nova:
   - o arquivo `.env`;
   - a pasta `dados\` inteira.
4. Ligue o Ghost no PC novo pelo `iniciar.bat`.

---

## 6. Problemas comuns

| Sintoma | Causa provável e solução |
|---|---|
| O `instalar.bat` fecha com erro de Python | Instale o Python 3.13 por python.org (marque "Add to PATH") e rode de novo |
| "não autorizado" ao abrir o `.bat` | Clique com o botão direito no arquivo > Propriedades > Desbloquear |
| Ele não ouve "Ghost" | Confira o microfone padrão do Windows; diga "Ghost, treinar ativação" |
| Ele responde sozinho a conversas da sala | Treine a ativação; em `ghost\voz\ativacao.py`, aumente `FATOR_DONO` |
| Ele para de falar sem motivo | Em `ghost\voz\ativacao.py`, aumente `FATOR_INTERRUPCAO` |
| Apareceu um arquivo `.corrompido` em `dados\` | Um arquivo foi gravado pela metade (ex.: queda de energia). O Ghost guardou a cópia e não grava por cima; apague o arquivo estragado (sem `.corrompido`) para recomeçar aquele item |
| Sem internet, ele só diz "estou sem internet" | É esperado: voz, transcrição e IA são na nuvem. Volta sozinho com a rede |
