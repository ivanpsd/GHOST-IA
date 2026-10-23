# GHOST - para o Ghost que está rodando oculto (o vigia não o reinicia). Rode pelo parar.bat.
. "$PSScriptRoot\comum.ps1"

Parar-Ghost
Ok "Ghost parado. Para rodar vendo o terminal: .\.venv\Scripts\python.exe -m ghost"
