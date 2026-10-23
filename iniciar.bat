@echo off
rem Inicia o GHOST oculto, com o vigia que o reinicia se cair.
cd /d "%~dp0"
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0vigia.pyw"
exit
