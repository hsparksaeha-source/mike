@echo off
chcp 65001 > nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
echo ================================================
echo   YouTube thumbnails - Flow background + CapCut
echo ================================================
python -u thumb_maker.py %*
echo.
pause
