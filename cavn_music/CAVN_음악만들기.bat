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
echo.
echo 만들 트랙 번호를 입력하세요. (예: 1  또는  1,3,5)
echo 그냥 Enter 를 누르면 전체를 만듭니다.
set "ONLY="
set /p ONLY=트랙 번호:
set "ONLYARG="
if not "%ONLY%"=="" set ONLYARG=--only "%ONLY%"
python -u cavn_maker.py "%MD%" %ONLYARG%
echo.
pause
