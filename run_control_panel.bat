@echo off
REM ============================================
REM  iNews Monitor - Panel de Control
REM  Inicia el servidor web y abre el navegador
REM ============================================

cd /d "%~dp0"

REM Activar entorno virtual si existe
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

set PORT=8080

echo.
echo ============================================
echo   iNews Monitor - Panel de Control
echo   Abriendo http://localhost:%PORT%
echo ============================================
echo.

REM Abrir el navegador tras un breve delay (para que el server arranque)
start "" cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:%PORT%"

REM Iniciar el servidor (bloquea hasta Ctrl+C)
python control_panel.py --port %PORT%

pause
