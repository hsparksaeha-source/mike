@echo off
chcp 65001 >nul
echo ================================================
echo   Open Chrome for Google verification only
echo   (same login as the auto-fill program, but a normal Chrome)
echo ================================================
echo.
echo 1. Close the auto-fill program's Chrome window first (all its windows).
echo 2. In the Chrome that opens: verify, choose the channel,
echo    and check that YouTube Studio opens normally.
echo 3. Close that Chrome completely, then run the v2 auto-fill bat.
echo.
pause
set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%LocalAppData%\Google\Chrome\Application\chrome.exe"
start "" "%CHROME%" --user-data-dir="C:\Users\lg\ChromeAutomationProfile" "https://studio.youtube.com/"
