@echo off
chcp 65001 >nul
echo ================================================
echo   CapCut Auto Assemble - Classical (2 rounds)
echo ================================================
echo.
echo Give the folder that directly contains the two required
echo subfolders (song files / image files).
echo.
echo Combined project order:
echo   round 1: every track title.wav
echo   round 2: every track title (1).wav
echo Images follow the track number (image folders 1, 2, 3 ...).
echo.
echo Tip: drag and drop the folder into this window instead of typing.
echo.
set /p PARENT=Source folder path:
echo.
echo Output folder: CapCut Drafts folder CapCut is using (usually under Documents).
echo Press Enter to use the default location.
set /p OUTDIR=Output CapCut Drafts folder (optional):
echo.
echo What to make?
echo   1) both (per-track projects + combined)
echo   2) combined project only
echo   3) per-track projects only
set MODE=1
set /p MODE=Choose 1, 2 or 3 (Enter = 1):
echo.
python -u "%~dp0capcut_assemble_classical_2pass.py" "%PARENT%" "%OUTDIR%" "%MODE%"
echo.
echo ================================================
echo   Done. You can close this window.
echo ================================================
pause
