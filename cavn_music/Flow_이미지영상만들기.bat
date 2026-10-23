@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo ================================================
echo   Google Flow 이미지 15장 + 영상 1개 자동 만들기
echo   (경음악·클래식 md 파일만)
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
python -u flow_maker.py "%MD%"
echo.
pause
