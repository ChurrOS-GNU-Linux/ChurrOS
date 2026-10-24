@echo off
chcp 65001 >nul
title ChurrOS - Nodo de Compilacion Distribuida (distcc)
setlocal enabledelayedexpansion

cd /d "%~dp0"

echo ========================================================
echo   ChurrOS - Iniciar Nodo Worker distcc en Windows
echo ========================================================
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-distcc-worker.ps1" %*

set EXIT_CODE=%ERRORLEVEL%
echo.
echo Presiona cualquier tecla para cerrar esta ventana...
pause >nul
exit /b %EXIT_CODE%
