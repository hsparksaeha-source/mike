@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo [1/2] 필요한 프로그램 설치 중...
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo 파이썬이 설치되어 있는지 확인해 주세요: https://www.python.org/downloads/
  pause
  exit /b 1
)
echo [2/2] 예비 브라우저 설치 중...
python -m playwright install chromium
echo.
echo 설치 완료! 이제 run.bat 을 더블클릭하세요.
pause
