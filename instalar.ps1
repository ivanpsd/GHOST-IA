# GHOST - instalação completa (primeira vez). Rode pelo instalar.bat.

$ErrorActionPreference = "Stop"
$Pasta = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Pasta
$Py = Join-Path $Pasta ".venv\Scripts\python.exe"
$PyW = Join-Path $Pasta ".venv\Scripts\pythonw.exe"

function Passo($t) { Write-Host ""; Write-Host "== $t" -ForegroundColor Cyan }
function Ok($t) { Write-Host "   ok: $t" -ForegroundColor Green }
function Aviso($t) { Write-Host "   atenção: $t" -ForegroundColor Yellow }

function Parar-Ghost {
    Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
        Where-Object { $_.CommandLine -match [regex]::Escape($Pasta) -and $_.CommandLine -match 'vigia.pyw|ghost.py' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
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
    & py -V:3.13 -c "print(1)" *> $null
    if ($LASTEXITCODE -ne 0) { throw "Python 3.13 não ficou disponível. Instale em python.org e rode de novo." }
    Ok "Python 3.13 instalado"
}

function Garantir-Ambiente {
    if (-not (Test-Path $Py)) { & py -V:3.13 -m venv .venv; Ok "ambiente .venv criado" }
    & $Py -m pip install --upgrade pip -q
    & $Py -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "falha ao instalar as bibliotecas (veja a mensagem acima)" }
    Ok "bibliotecas instaladas"
}

function Garantir-Ollama {
    $exe = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
    if (Test-Path $exe) { Ok "Ollama já instalado"; return }
    winget install --id Ollama.Ollama -e --silent --accept-package-agreements --accept-source-agreements
    if (Test-Path $exe) { Ok "Ollama instalado" } else { Aviso "Ollama não instalou; o modo sem internet fica sem IA local" }
}

function Garantir-Vosk {
    $dir = Join-Path $Pasta "modelos\vosk-model-small-en-us-0.15"
    if (Test-Path $dir) { Ok "modelo Vosk já existe"; return }
    New-Item -ItemType Directory -Force (Join-Path $Pasta "modelos") | Out-Null
    $zip = Join-Path $env:TEMP "vosk-small-en.zip"
    Invoke-WebRequest "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip" -OutFile $zip
    Expand-Archive $zip -DestinationPath (Join-Path $Pasta "modelos") -Force
    Remove-Item $zip
    Ok "modelo Vosk baixado"
}

function Criar-Atalho-Inicializacao {
    $ws = New-Object -ComObject WScript.Shell
    $lnk = $ws.CreateShortcut((Join-Path ([Environment]::GetFolderPath("Startup")) "GHOST.lnk"))
    $lnk.TargetPath = $PyW
    $lnk.Arguments = "`"$(Join-Path $Pasta 'vigia.pyw')`""
    $lnk.WorkingDirectory = $Pasta
    $lnk.Save()
    Ok "Ghost inicia junto com o Windows (atalho GHOST na Inicialização)"
}

function Iniciar-Ghost {
    Start-Process -FilePath $PyW -ArgumentList "`"$(Join-Path $Pasta 'vigia.pyw')`"" -WorkingDirectory $Pasta
    Ok "Ghost iniciado (oculto). Acompanhe em ghost.log"
}

Passo "1/7 Python 3.13";            Garantir-Python313
Passo "2/7 Bibliotecas (.venv)";    Garantir-Ambiente
Passo "3/7 Chaves (.env)"
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Aviso "criei o .env: coloque GROQ_API_KEY e GEMINI_API_KEY, salve e feche o Bloco de Notas para continuar"
    Start-Process notepad.exe ".env" -Wait
} else { Ok ".env já existe (mantido)" }
Passo "4/7 Ollama (IA sem internet)"; Garantir-Ollama
Passo "5/7 Palavra de ativação (Vosk)"; Garantir-Vosk
Passo "6/7 Modelos locais (~4 GB, demora na 1ª vez)"
& $Py instalar_modelos.py
Passo "7/7 Inicialização com o Windows"; Parar-Ghost; Criar-Atalho-Inicializacao; Iniciar-Ghost
Write-Host ""
Write-Host "Pronto. Diga 'Ghost, treinar ativação' para ele aprender a sua voz." -ForegroundColor Green
