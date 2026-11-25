@echo off
chcp 65001 > nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
echo ================================================
echo   Google Flow - 15 images + 1 video per track
echo ================================================
python -u flow_maker.py %*
echo.
pause
