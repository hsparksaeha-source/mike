@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo ================================================
echo   CAVN AI 자동 곡 만들기 + 다운로드
echo ================================================
echo.
set "MD=%~1"
if not "%MD%"=="" goto run
echo 음악 md 파일을 이 창에 끌어다 놓고 Enter 를 누르세요:
set /p MD=
set MD=%MD:"=%
if "%MD%"=="" (
  echo md 파일이 없어서 끝냅니다.
  pause
  exit /b 1
)
:run
python -u cavn_maker.py "%MD%"
echo.
pause
