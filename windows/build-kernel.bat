@echo off
chcp 65001 >nul
title Compilador de Kernel ChurrOS - Windows
setlocal enabledelayedexpansion

cd /d "%~dp0"

echo ========================================================
echo   ChurrOS - Compilacion de Kernel para Windows
echo ========================================================
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build-kernel.ps1" %*

set EXIT_CODE=%ERRORLEVEL%
echo.
if %EXIT_CODE% EQU 0 (
    echo [OK] Proceso finalizado correctamente.
) else (
    echo [ERROR] Ocurrio un problema durante la ejecucion (codigo %EXIT_CODE%).
)
echo.
echo Presiona cualquier tecla para cerrar esta ventana...
pause >nul
exit /b %EXIT_CODE%
