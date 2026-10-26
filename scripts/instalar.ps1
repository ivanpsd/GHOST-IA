# GHOST - instalação completa (primeira vez). Rode pelo instalar.bat.
. "$PSScriptRoot\comum.ps1"

Parar-Ghost                         # reinstalação: o Ghost não pode estar usando o .venv
Passo "1/6 Python 3.13";            Garantir-Python313
Passo "2/6 Bibliotecas (.venv)";    Garantir-Ambiente
Passo "3/6 Chaves (.env)"
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Aviso "criei o .env: coloque GROQ_API_KEY e GEMINI_API_KEY, salve e feche o Bloco de Notas para continuar"
    Start-Process notepad.exe ".env" -Wait
} else { Ok ".env já existe (mantido)" }
Passo "4/6 Palavra de ativação (Vosk)";     Garantir-Vosk
Passo "5/6 Modelos locais (~400 MB)"; Baixar-Modelos
Passo "6/6 Inicialização com o Windows";    Parar-Ghost; Criar-Atalho-Inicializacao; Iniciar-Ghost
Write-Host ""
Write-Host "Pronto. Diga 'Ghost, treinar ativação' para ele aprender a sua voz." -ForegroundColor Green
