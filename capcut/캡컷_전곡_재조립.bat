@echo off
chcp 65001 > nul
setlocal

echo CapCut Drafts folder path (drag and drop the folder here):
set /p DRAFTS=

if "%DRAFTS%"=="" (
  echo No folder given. Closing.
  pause
  exit /b 1
)

set DRAFTS=%DRAFTS:"=%

python -u "%~dp0capcut_merge_edited_projects.py" "%DRAFTS%"

echo.
pause
