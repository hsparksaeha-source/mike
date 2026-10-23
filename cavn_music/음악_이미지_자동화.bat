@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo ================================================
echo   음악 · 이미지 자동화
echo ================================================
echo.
set "MD=%~1"
if not "%MD%"=="" goto menu
echo 음악 md 파일을 이 창에 끌어다 놓고 Enter 를 누르세요:
set /p MD=
set MD=%MD:"=%
if "%MD%"=="" (
  echo md 파일이 없어서 끝냅니다.
  pause
  exit /b 1
)
:menu
echo.
echo   1 = 음악 만들기 (CAVN AI)
echo   2 = 이미지 15장 + 영상 만들기 (Google Flow, 경음악·클래식만)
echo   3 = 둘 다 (음악 먼저, 이어서 이미지)
echo.
set /p CHOICE=번호를 고르세요 (1/2/3):
if "%CHOICE%"=="1" python -u cavn_maker.py "%MD%"
if "%CHOICE%"=="2" python -u flow_maker.py "%MD%"
if "%CHOICE%"=="3" (
  python -u cavn_maker.py "%MD%"
  python -u flow_maker.py "%MD%"
)
echo.
pause
