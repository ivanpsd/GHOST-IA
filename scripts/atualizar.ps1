# GHOST - atualização: baixa a última versão do GitHub e reaplica tudo. Rode pelo atualizar.bat.
# Seus dados (pasta dados\), e o .env não são tocados.
param([switch]$DepoisDoPull)
. "$PSScriptRoot\comum.ps1"

if (-not $DepoisDoPull) {
    Passo "1/4 Parando o Ghost"; Parar-Ghost; Ok "parado"
    Passo "2/4 Baixando a última versão do GitHub"
    if (-not (Test-Path ".git")) { throw "esta pasta não veio do git clone; baixe de novo com: git clone https://github.com/ivanpsd/GHOST-IA.git" }
    git pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw "o git pull falhou (há alterações locais nos arquivos do projeto?). Veja: git status" }
    Ok "código atualizado"
    # o resto roda com a versão NOVA deste script (pode ter mudado no pull)
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Pasta "scripts\atualizar.ps1") -DepoisDoPull
    exit $LASTEXITCODE
}

Passo "3/4 Python e bibliotecas"; Garantir-Python313; Garantir-Ambiente
Passo "4/4 Reiniciando"; Parar-Ghost; Criar-Atalhos; Iniciar-Ghost
Write-Host ""
Write-Host "Atualizado. Suas memórias, fichas, skills e .env foram mantidos." -ForegroundColor Green
