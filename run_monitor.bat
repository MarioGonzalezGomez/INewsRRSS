@echo off
cd /d "%~dp0"
echo Iniciando iNews Monitor...
env\Scripts\python.exe inews_monitor.py %*
pause
