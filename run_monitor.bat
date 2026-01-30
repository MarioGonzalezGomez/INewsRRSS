@echo off
setlocal enabledelayedexpansion

REM Cambiar al directorio del script
cd /d "%~dp0"

REM Intenta usar el entorno virtual local
if exist "env\Scripts\python.exe" (
    echo Usando Python del entorno virtual local...
    set PYTHON_PATH=env\Scripts\python.exe
) else (
    REM Si el entorno virtual no existe, intenta Python del PATH del sistema
    echo Entorno virtual no encontrado. Buscando Python en el PATH del sistema...
    for /f "tokens=*" %%i in ('where python 2^>nul') do set PYTHON_PATH=%%i
    
    if "!PYTHON_PATH!"=="" (
        echo.
        echo ERROR: No se encontro Python en el sistema.
        echo.
        echo Soluciones:
        echo 1. Reinstala el entorno virtual: python -m venv env
        echo 2. Instala Python desde https://www.python.org (marca "Add Python to PATH")
        echo.
        pause
        exit /b 1
    )
)

echo Iniciando iNews Monitor con Python: !PYTHON_PATH!
"!PYTHON_PATH!" inews_monitor.py %*
pause
