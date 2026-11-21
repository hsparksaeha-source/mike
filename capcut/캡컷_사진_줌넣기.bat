@echo off
chcp 65001 >nul
echo ================================================
echo   CapCut - slow zoom on every photo clip
echo ================================================
echo.
echo IMPORTANT: close CapCut completely before continuing.
echo.
echo Give the "CapCut Drafts" folder (all projects inside get the zoom),
echo or the album folder that contains it, or one project folder.
echo This is the same output folder you gave the assemble program.
echo.
echo Tip: drag and drop the folder into this window instead of typing.
echo.
set /p DRAFTS=CapCut Drafts folder path:
echo.
echo Each photo starts at 100%% and grows to this size at its end.
echo Type a number like 110, 115 or 120.
set /p ENDPCT=End size %% (Enter = 115):
echo.
python -u "C:\Users\lg\Desktop\yt_automation\capcut_zoom_keyframes.py" "%DRAFTS%" "%ENDPCT%"
echo.
echo ================================================
echo   Done. You can close this window.
echo ================================================
pause
