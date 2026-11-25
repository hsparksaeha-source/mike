@echo off
chcp 65001 > nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
echo ================================================
echo   CAVN AI - make songs and download
echo ================================================
python -u cavn_maker.py %*
echo.
pause
