# GHOST - instalação completa (primeira vez). Rode pelo instalar.bat.
. "$PSScriptRoot\comum.ps1"

Parar-Ghost                         # reinstalação: o Ghost não pode estar usando o .venv
Passo "1/7 Python 3.13";            Garantir-Python313
Passo "2/7 Bibliotecas (.venv)";    Garantir-Ambiente
Passo "3/7 Chaves (.env)"
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Aviso "criei o .env: coloque GROQ_API_KEY e GEMINI_API_KEY, salve e feche o Bloco de Notas para continuar"
    Start-Process notepad.exe ".env" -Wait
} else { Ok ".env já existe (mantido)" }
Passo "4/7 Ollama (IA sem internet)";       Garantir-Ollama
Passo "5/7 Palavra de ativação (Vosk)";     Garantir-Vosk
Passo "6/7 Modelos locais (~4 GB, demora na 1ª vez)"; Baixar-Modelos
Passo "7/7 Inicialização com o Windows";    Parar-Ghost; Criar-Atalho-Inicializacao; Iniciar-Ghost
Write-Host ""
Write-Host "Pronto. Diga 'Ghost, treinar ativação' para ele aprender a sua voz." -ForegroundColor Green
