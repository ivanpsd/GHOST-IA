@echo off
rem Tudo numa linha: o git pull pode trocar este arquivo enquanto ele roda.
cd /d "%~dp0" & powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\atualizar.ps1" & pause & exit /b
