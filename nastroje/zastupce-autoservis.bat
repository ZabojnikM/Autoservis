@echo off
rem Dvojklik: vytvori zastupce Autoservis na plose a v nabidce Start (zepta se na adresu serveru).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0zastupce-autoservis.ps1" %*
pause
