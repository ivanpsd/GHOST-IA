# GHOST - roda os testes automáticos e a checagem do código. Rode pelo testar.bat.
. "$PSScriptRoot\comum.ps1"

if (-not (Test-Path $Py)) { throw "rode o instalar.bat primeiro" }
& $Py -m pip install -q --disable-pip-version-check -r requirements-dev.txt
Passo "Checagem do código (ruff)"
& $Py -m ruff check ghost tests
$lint = $LASTEXITCODE
Passo "Testes (pytest)"
& $Py -m pytest
$testes = $LASTEXITCODE
Write-Host ""
if ($lint -eq 0 -and $testes -eq 0) { Write-Host "Tudo certo." -ForegroundColor Green; exit 0 }
Write-Host "Há falhas (veja acima)." -ForegroundColor Red; exit 1
