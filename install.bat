@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo [1/2] Installing required Python packages...
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo Please check that Python is installed: https://www.python.org/downloads/
  pause
  exit /b 1
)
echo [2/2] Installing backup browser...
python -m playwright install chromium
echo.
echo Done! Now run the program bat file.
pause
