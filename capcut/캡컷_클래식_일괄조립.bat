@echo off
chcp 65001 >nul
echo ================================================
echo   CapCut Auto Assemble - Classical (batch)
echo ================================================
echo.
echo Give the folder that directly contains the two required
echo subfolders (song files / image files).
echo Do not give the subfolder itself - give the folder one level above it.
echo.
echo Songs (wav only, mp3 ignored) are paired 2-by-2 by file date.
echo Images are grouped in chunks of 15 by file date.
echo Each pair+chunk becomes one CapCut project automatically.
echo.
echo Tip: drag and drop the folder into this window instead of typing.
echo.
set /p PARENT=Source folder path:
echo.
echo Output folder: this should be the real CapCut Drafts folder
echo CapCut is using for this project (usually under Documents).
echo Press Enter to just save inside the source folder instead.
set /p OUTDIR=Output CapCut Drafts folder (optional):
echo.
python -u "C:\Users\lg\Desktop\yt_automation\capcut_assemble_classical.py" "%PARENT%" "%OUTDIR%"
echo.
echo ================================================
echo   Done. You can close this window.
echo ================================================
pause
