# GHOST - atualização: baixa a última versão do GitHub e reaplica tudo. Rode pelo atualizar.bat.
# Seus dados (pasta dados\), o .env e os modelos não são tocados.
param([switch]$DepoisDoPull)
. "$PSScriptRoot\comum.ps1"

if (-not $DepoisDoPull) {
    Passo "1/5 Parando o Ghost"; Parar-Ghost; Ok "parado"
    Passo "2/5 Baixando a última versão do GitHub"
    if (-not (Test-Path ".git")) { throw "esta pasta não veio do git clone; baixe de novo com: git clone https://github.com/ivanpsd/GHOST-IA.git" }
    git pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw "o git pull falhou (há alterações locais nos arquivos do projeto?). Veja: git status" }
    Ok "código atualizado"
    # o resto roda com a versão NOVA deste script (pode ter mudado no pull)
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Pasta "scripts\atualizar.ps1") -DepoisDoPull
    exit $LASTEXITCODE
}

Passo "3/5 Python e bibliotecas"; Garantir-Python313; Garantir-Ambiente
Passo "4/5 Modelos (só baixa o que faltar)"; Garantir-Ollama; Garantir-Vosk; Baixar-Modelos
Passo "5/5 Reiniciando"; Parar-Ghost; Criar-Atalho-Inicializacao; Iniciar-Ghost
Write-Host ""
Write-Host "Atualizado. Suas memórias, fichas, skills e .env foram mantidos." -ForegroundColor Green
