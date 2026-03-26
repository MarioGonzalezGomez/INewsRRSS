@echo off
setlocal enabledelayedexpansion

REM ============================================
REM  iNews Monitor - Arranque Completo
REM  Inicia Panel Web + Monitor de Descarga
REM ============================================

cd /d "%~dp0"

set PYTHON_PATH=
if exist "env\Scripts\python.exe" (
    set PYTHON_PATH=env\Scripts\python.exe
) else if exist "venv\Scripts\python.exe" (
    set PYTHON_PATH=venv\Scripts\python.exe
) else (
    for /f "tokens=*" %%i in ('where python 2^>nul') do set PYTHON_PATH=%%i
)

if "!PYTHON_PATH!"=="" (
    echo.
    echo ERROR: No se encontro Python.
    echo Ejecuta setup_env.bat o instala Python en PATH.
    echo.
    pause
    exit /b 1
)

set PORT=8080

echo.
echo ============================================
echo   iNews Monitor - Arranque Completo
echo   UI: http://localhost:%PORT%
echo   Monitor: activado en segundo plano
echo ============================================
echo.

start "" cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:%PORT%"
"!PYTHON_PATH!" control_panel.py --port %PORT% --with-monitor

pause
