@echo off
setlocal enabledelayedexpansion

echo ============================================
echo Configurando entorno virtual para AppTuits
echo ============================================
echo.

REM Cambiar al directorio del script
cd /d "%~dp0"

REM Buscar Python en rutas estándar primero
echo Buscando Python...
set PYTHON_PATH=

if exist "C:\Python311\python.exe" (
    set PYTHON_PATH=C:\Python311\python.exe
) else if exist "C:\Python310\python.exe" (
    set PYTHON_PATH=C:\Python310\python.exe
) else if exist "C:\Python312\python.exe" (
    set PYTHON_PATH=C:\Python312\python.exe
) else if exist "C:\Python39\python.exe" (
    set PYTHON_PATH=C:\Python39\python.exe
) else (
    REM Si no está en rutas estándar, intentar desde PATH
    for /f "tokens=*" %%i in ('where python 2^>nul ^| findstr /v WindowsApps') do (
        set PYTHON_PATH=%%i
        goto :found
    )
)

:found
if "!PYTHON_PATH!"=="" (
    echo ERROR: No se encontro Python en el sistema
    echo.
    echo Por favor instala Python desde https://www.python.org
    echo Descarga Python 3.10, 3.11 o 3.12
    echo.
    pause
    exit /b 1
)

echo Encontrado: !PYTHON_PATH!
"!PYTHON_PATH!" --version
echo.

if exist "env" (
    echo Eliminando entorno virtual anterior...
    rmdir /s /q env
)

echo Creando entorno virtual...
"!PYTHON_PATH!" -m venv env

if errorlevel 1 (
    echo ERROR al crear el entorno virtual
    pause
    exit /b 1
)

echo Instalando dependencias...
call env\Scripts\pip install --upgrade pip -q
call env\Scripts\pip install -r requirements.txt

if errorlevel 1 (
    echo ERROR al instalar dependencias
    pause
    exit /b 1
)

echo.
echo ============================================
echo Listo! Ejecuta: run_monitor.bat
echo ============================================
pause
