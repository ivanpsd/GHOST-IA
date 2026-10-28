# GHOST - instalação completa (primeira vez). Rode pelo instalar.bat.
. "$PSScriptRoot\comum.ps1"

Parar-Ghost                         # reinstalação: o Ghost não pode estar usando o .venv
Passo "1/4 Python 3.13";            Garantir-Python313
Passo "2/4 Bibliotecas (.venv)";    Garantir-Ambiente
Passo "3/4 Chaves (.env)"
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Aviso "criei o .env: coloque GROQ_API_KEY e GEMINI_API_KEY, salve e feche o Bloco de Notas para continuar"
    Start-Process notepad.exe ".env" -Wait
} else { Ok ".env já existe (mantido)" }
Passo "4/4 Atalhos e inicialização com o Windows";    Parar-Ghost; Criar-Atalhos; Iniciar-Ghost
Write-Host ""
Write-Host "Pronto. Segure F9, fale e solte. O GHOST também está no Menu Iniciar." -ForegroundColor Green
