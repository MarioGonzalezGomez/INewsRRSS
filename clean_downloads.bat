@echo off
setlocal enabledelayedexpansion
REM ============================================
REM Script de Limpieza Manual de Descargas
REM ============================================
REM Este script elimina TODAS las carpetas de tweets descargados.
REM Usa comandos con permisos elevados para manejar carpetas bloqueadas.
REM 
REM USO:
REM   1. Ejecutar como administrador si hay problemas de permisos
REM   2. Cerrar cualquier aplicación que pueda tener archivos abiertos
REM ============================================

cd /d "%~dp0"

REM Leer ruta de descarga desde config.json (si existe)
set DOWNLOAD_PATH=Descargas

REM Intentar leer de config.json usando PowerShell
for /f "usebackq delims=" %%i in (`powershell -Command "(Get-Content -Raw 'config.json' 2>$null | ConvertFrom-Json).content.download_base_path" 2^>nul`) do (
    if not "%%i"=="" set DOWNLOAD_PATH=%%i
)

echo ============================================
echo LIMPIEZA DE DESCARGAS DE TWEETS
echo ============================================
echo.
echo Ruta de descargas: %DOWNLOAD_PATH%
echo.

if not exist "%DOWNLOAD_PATH%" (
    echo ERROR: La carpeta de descargas no existe: %DOWNLOAD_PATH%
    pause
    exit /b 1
)

echo ADVERTENCIA: Esto eliminara TODAS las carpetas de tweets descargados.
echo El archivo index.csv y content_state.json tambien seran eliminados.
echo.
set /p CONFIRM="¿Estas seguro? (S/N): "
if /i not "%CONFIRM%"=="S" (
    echo Operacion cancelada.
    pause
    exit /b 0
)

echo.
echo Iniciando limpieza...
echo.

REM Eliminar el archivo de estado primero
if exist "%DOWNLOAD_PATH%\content_state.json" (
    echo Eliminando content_state.json...
    del /f /q "%DOWNLOAD_PATH%\content_state.json" 2>nul
    if exist "%DOWNLOAD_PATH%\content_state.json" (
        echo   [!] No se pudo eliminar content_state.json
    ) else (
        echo   [OK] content_state.json eliminado
    )
)

REM Eliminar index.csv
if exist "%DOWNLOAD_PATH%\index.csv" (
    echo Eliminando index.csv...
    del /f /q "%DOWNLOAD_PATH%\index.csv" 2>nul
    if exist "%DOWNLOAD_PATH%\index.csv" (
        echo   [!] No se pudo eliminar index.csv
    ) else (
        echo   [OK] index.csv eliminado
    )
)

REM Eliminar archivos temporales
echo Eliminando archivos temporales...
del /f /q "%DOWNLOAD_PATH%\*.tmp" 2>nul

REM Eliminar cada subcarpeta (las carpetas de tweets tienen nombres numericos)
echo.
echo Eliminando carpetas de tweets...
set COUNT=0
set ERRORS=0

for /d %%D in ("%DOWNLOAD_PATH%\*") do (
    REM Verificar si es una carpeta con nombre numerico (ID de tweet)
    echo %%~nxD | findstr /r "^[0-9]*$" >nul
    if !errorlevel!==0 (
        echo Eliminando: %%~nxD
        
        REM Metodo 1: rmdir normal
        rmdir /s /q "%%D" 2>nul
        
        if exist "%%D" (
            REM Metodo 2: Quitar atributos y reintentar
            echo   Reintentando con attrib...
            attrib -r -s -h "%%D\*.*" /s /d 2>nul
            rmdir /s /q "%%D" 2>nul
        )
        
        if exist "%%D" (
            REM Metodo 3: Tomar propiedad (requiere admin)
            echo   Reintentando con takeown...
            takeown /f "%%D" /r /d y >nul 2>&1
            icacls "%%D" /grant %USERNAME%:F /t >nul 2>&1
            rmdir /s /q "%%D" 2>nul
        )
        
        if exist "%%D" (
            REM Metodo 4: Usar robocopy con carpeta vacia
            echo   Reintentando con robocopy...
            mkdir "%TEMP%\empty_dir" 2>nul
            robocopy "%TEMP%\empty_dir" "%%D" /mir /r:1 /w:1 >nul 2>&1
            rmdir /s /q "%%D" 2>nul
            rmdir "%TEMP%\empty_dir" 2>nul
        )
        
        if exist "%%D" (
            echo   [ERROR] No se pudo eliminar: %%~nxD
            set /a ERRORS+=1
        ) else (
            echo   [OK] Eliminado: %%~nxD
            set /a COUNT+=1
        )
    )
)

REM Eliminar TempVideo si existe
if exist "%DOWNLOAD_PATH%\TempVideo" (
    echo Eliminando carpeta TempVideo...
    rmdir /s /q "%DOWNLOAD_PATH%\TempVideo" 2>nul
)

echo.
echo ============================================
echo LIMPIEZA COMPLETADA
echo ============================================
echo Carpetas eliminadas: %COUNT%
if %ERRORS% gtr 0 (
    echo Errores: %ERRORS%
    echo.
    echo NOTA: Algunas carpetas no pudieron eliminarse.
    echo Posibles causas:
    echo   - Archivos abiertos por otra aplicacion
    echo   - Permisos insuficientes (ejecutar como administrador)
    echo   - Carpetas bloqueadas por el servidor de red
)
echo.
pause
