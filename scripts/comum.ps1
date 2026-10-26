# GHOST - funções usadas pelos scripts de instalação, atualização e parada.
# Não rode este arquivo sozinho: ele é carregado pelos outros (". $PSScriptRoot\comum.ps1").

$ErrorActionPreference = "Stop"
# PowerShell 5.1 pode tentar TLS antigo e falhar nos downloads ("Could not create SSL/TLS secure channel")
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$Pasta = Split-Path -Parent $PSScriptRoot          # a pasta do Ghost (um nível acima de scripts\)
Set-Location $Pasta
$Py  = Join-Path $Pasta ".venv\Scripts\python.exe"
$PyW = Join-Path $Pasta ".venv\Scripts\pythonw.exe"
$Atalho = Join-Path ([Environment]::GetFolderPath("Startup")) "GHOST.lnk"

function Passo($t) { Write-Host ""; Write-Host "== $t" -ForegroundColor Cyan }
function Ok($t)    { Write-Host "   ok: $t" -ForegroundColor Green }
function Aviso($t) { Write-Host "   atenção: $t" -ForegroundColor Yellow }

function Parar-Ghost {
    # Versão nova: "-m ghost" / "-m ghost.vigia" (só existe um Ghost por usuário: o próprio Ghost garante isso).
    # Versão antiga: "vigia.pyw" / "ghost.py" desta pasta.
    $alvos = @(Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object {
        $_.CommandLine -and (
            $_.CommandLine -match '-m\s+"?ghost(\.vigia)?"?(\s|$)' -or
            ($_.CommandLine -match [regex]::Escape($Pasta) -and $_.CommandLine -match 'vigia\.pyw|ghost\.py'))
    })
    # o vigia primeiro (senão ele reabre o Ghost que acabou de ser parado)
    $alvos | Sort-Object { if ($_.CommandLine -match 'vigia') { 0 } else { 1 } } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    if ($alvos.Count) { Start-Sleep -Milliseconds 800 }
}

function Garantir-Python313 {
    $tem = $false
    try { & py -V:3.13 -c "print(1)" *> $null; $tem = ($LASTEXITCODE -eq 0) } catch { }
    if ($tem) { Ok "Python 3.13 encontrado"; return }
    Write-Host "   instalando Python 3.13..."
    $ok = $false
    try { & py install 3.13; $ok = ($LASTEXITCODE -eq 0) } catch { }
    if (-not $ok) {
        winget install --id Python.Python.3.13 -e --silent --accept-package-agreements --accept-source-agreements
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
    }
    $tem = $false
    try { & py -V:3.13 -c "print(1)" *> $null; $tem = ($LASTEXITCODE -eq 0) } catch { }
    if (-not $tem) { throw "Python 3.13 não ficou disponível. Instale em python.org e rode de novo." }
    Ok "Python 3.13 instalado"
}

function Garantir-Ambiente {
    if (Test-Path $Py) {
        $versao = ""
        try { $versao = (& $Py -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null) } catch { }
        if ($versao -ne "3.13") {
            Aviso "o .venv é de outro Python ($versao); recriando com o 3.13"
            Remove-Item -Recurse -Force (Join-Path $Pasta ".venv")
        }
    }
    if (-not (Test-Path $Py)) {
        & py -V:3.13 -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw "não consegui criar o ambiente .venv" }
        Ok "ambiente .venv criado"
    }
    & $Py -m pip install --upgrade pip -q --disable-pip-version-check
    Write-Host "   instalando/conferindo bibliotecas (na 1ª vez demora alguns minutos)..."
    & $Py -m pip install -q --disable-pip-version-check -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "falha ao instalar as bibliotecas (veja a mensagem acima)" }
    Ok "bibliotecas instaladas"
}

function Garantir-Vosk {
    $modelos = Join-Path $Pasta "modelos"
    $dir = Join-Path $modelos "vosk-model-small-en-us-0.15"
    if (Test-Path (Join-Path $dir "am")) { Ok "modelo Vosk já existe"; return }
    New-Item -ItemType Directory -Force $modelos | Out-Null
    $zip = Join-Path $env:TEMP "vosk-small-en.zip"
    Invoke-WebRequest "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip" -OutFile $zip -UseBasicParsing
    Expand-Archive $zip -DestinationPath $modelos -Force
    Remove-Item $zip -ErrorAction SilentlyContinue
    Ok "modelo Vosk baixado"
}

function Baixar-Modelos {
    & $Py -m ghost.instalar_modelos
    if ($LASTEXITCODE -ne 0) { Aviso "algum modelo não baixou (veja acima); o resto funciona e dá para rodar de novo depois" }
}

function Criar-Atalho-Inicializacao {
    $ws = New-Object -ComObject WScript.Shell
    $lnk = $ws.CreateShortcut($Atalho)
    $lnk.TargetPath = $PyW
    $lnk.Arguments = "-m ghost.vigia"
    $lnk.WorkingDirectory = $Pasta
    $lnk.Description = "GHOST - assistente por voz"
    $lnk.Save()
    Ok "Ghost inicia junto com o Windows (atalho GHOST na Inicialização)"
}

function Iniciar-Ghost {
    Start-Process -FilePath $PyW -ArgumentList "-m", "ghost.vigia" -WorkingDirectory $Pasta
    Ok "Ghost iniciado (oculto). Acompanhe em logs\ghost.log"
}
