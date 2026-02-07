@echo off
setlocal
cd /d "%~dp0"
echo ============================================
echo FIXING PERMISSIONS FOR DOWNLOADS FOLDER
echo ============================================
echo.

set DOWNLOAD_PATH=Descargas
for /f "usebackq delims=" %%i in (`powershell -Command "(Get-Content -Raw 'config.json' 2>$null | ConvertFrom-Json).content.download_base_path" 2^>nul`) do (
    if not "%%i"=="" set DOWNLOAD_PATH=%%i
)

if not exist "%DOWNLOAD_PATH%" (
    echo [ERROR] Downloads folder not found: %DOWNLOAD_PATH%
    pause
    exit /b 1
)

echo Granting Full Control to Everyone/Todos for: %DOWNLOAD_PATH%
echo This may take a moment...
echo.

REM Grant access to "Everyone" (English Windows)
icacls "%DOWNLOAD_PATH%" /grant Everyone:F /t /c /q
REM Grant access to "Todos" (Spanish Windows)
icacls "%DOWNLOAD_PATH%" /grant Todos:F /t /c /q

echo.
echo ============================================
echo PERMISSIONS UPDATED
echo ============================================
pause
