@echo off
setlocal enabledelayedexpansion

REM =============================================
REM  Panel de Control - iNews Monitor
REM  Abre un servidor web en el puerto 8080
REM  para gestionar perfiles y monitores
REM =============================================

REM Cambiar al directorio del script
cd /d "%~dp0"

REM Intenta usar el entorno virtual local
if exist "env\Scripts\python.exe" (
    echo Usando Python del entorno virtual local...
    set PYTHON_PATH=env\Scripts\python.exe
) else (
    echo Entorno virtual no encontrado. Buscando Python en el PATH del sistema...
    for /f "tokens=*" %%i in ('where python 2^>nul') do set PYTHON_PATH=%%i
    
    if "!PYTHON_PATH!"=="" (
        echo.
        echo ERROR: No se encontro Python en el sistema.
        echo.
        pause
        exit /b 1
    )
)

echo.
echo ======================================================
echo   iNews Monitor - Panel de Control
echo   Abriendo en http://localhost:8080
echo ======================================================
echo.

start http://localhost:8080
"!PYTHON_PATH!" control_panel.py %*
pause
